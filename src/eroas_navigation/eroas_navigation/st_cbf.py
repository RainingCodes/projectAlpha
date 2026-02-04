"""
ST-CBF: Spatio-Temporal Control Barrier Function
Enforces safety constraints through QP-based filtering
Based on EROAS paper Section III-C3
"""

import numpy as np
from typing import Tuple, Optional

# Try to import cvxpy for QP solving
try:
    import cvxpy as cp
    CVXPY_AVAILABLE = True
except ImportError:
    CVXPY_AVAILABLE = False
    print("WARNING: cvxpy not available. ST-CBF will use simplified safety filter.")


class STCBF:
    """
    Spatio-Temporal Control Barrier Function

    Filters nominal reference commands to ensure safety through
    barrier function constraints
    """

    def __init__(self,
                 obstacle_radius: float = 2.0,
                 cbf_gain: float = 1.0,
                 v_max: float = 1.0):
        """
        Initialize ST-CBF

        Args:
            obstacle_radius: Conservative obstacle radius (Ro) in meters
            cbf_gain: CBF class-K function gain (k)
            v_max: Maximum velocity
        """
        self.R_o = obstacle_radius
        self.k = cbf_gain
        self.v_max = v_max

    def filter(self,
               v_ref: np.ndarray,
               vehicle_pos: np.ndarray,
               obstacle_pos: Optional[np.ndarray],
               mode: str = 'H') -> np.ndarray:
        """
        Filter reference velocity through CBF constraint (Equations 31-35)

        Args:
            v_ref: Reference velocity [vx, vy, vz]
            vehicle_pos: Vehicle position [x, y, z]
            obstacle_pos: Closest obstacle position [x, y, z], or None
            mode: 'H' for horizontal, 'V' for vertical

        Returns:
            Safe velocity command
        """
        if obstacle_pos is None:
            # No obstacles - return reference as is
            return v_ref

        # Calculate barrier function h (Equation 31)
        h = self._compute_barrier(vehicle_pos, obstacle_pos, mode)

        if h > 2.0:  # Far from obstacle
            return v_ref

        # Compute barrier derivative constraint (Equation 34)
        h_dot = self._compute_barrier_derivative(
            vehicle_pos, obstacle_pos, v_ref, mode
        )

        # Check if nominal velocity is safe
        if h_dot >= -self.k * h:
            return v_ref

        # Use QP to find safe velocity
        if CVXPY_AVAILABLE:
            return self._solve_qp(v_ref, h, vehicle_pos, obstacle_pos, mode)
        else:
            # Fallback: simple projection
            return self._simple_projection(v_ref, h, vehicle_pos, obstacle_pos, mode)

    def _compute_barrier(self,
                        vehicle_pos: np.ndarray,
                        obstacle_pos: np.ndarray,
                        mode: str) -> float:
        """
        Compute barrier function value (Equation 31)
        h(pv, t) = ||pv - po||² - R²o
        """
        if mode == 'H':
            # Horizontal: XY distance
            dist_sq = (
                (vehicle_pos[0] - obstacle_pos[0])**2 +
                (vehicle_pos[1] - obstacle_pos[1])**2
            )
        elif mode == 'V':
            # Vertical: XZ distance
            dist_sq = (
                (vehicle_pos[0] - obstacle_pos[0])**2 +
                (vehicle_pos[2] - obstacle_pos[2])**2
            )
        else:
            # Full 3D
            dist_sq = np.sum((vehicle_pos - obstacle_pos)**2)

        h = dist_sq - self.R_o**2
        return h

    def _compute_barrier_derivative(self,
                                   vehicle_pos: np.ndarray,
                                   obstacle_pos: np.ndarray,
                                   velocity: np.ndarray,
                                   mode: str) -> float:
        """
        Compute barrier function time derivative
        h_dot = 2 * (pv - po)^T * v
        """
        if mode == 'H':
            # Horizontal: only XY components
            delta = vehicle_pos[:2] - obstacle_pos[:2]
            v = velocity[:2]
        elif mode == 'V':
            # Vertical: XZ components
            delta = vehicle_pos[[0, 2]] - obstacle_pos[[0, 2]]
            v = velocity[[0, 2]]
        else:
            # Full 3D
            delta = vehicle_pos - obstacle_pos
            v = velocity

        h_dot = 2.0 * np.dot(delta, v)
        return h_dot

    def _solve_qp(self,
                  v_ref: np.ndarray,
                  h: float,
                  vehicle_pos: np.ndarray,
                  obstacle_pos: np.ndarray,
                  mode: str) -> np.ndarray:
        """
        Solve QP to find safe velocity (Equations 33-35)

        min ||v - v_ref||²
        s.t. h_dot >= -k*h
        """
        # Determine active dimensions
        if mode == 'H':
            active_dims = 2  # XY
            a_coeff = 1.0
            b_coeff = 0.0
        elif mode == 'V':
            active_dims = 2  # XZ (but indices [0, 2])
            a_coeff = 0.0
            b_coeff = 1.0
        else:
            active_dims = 3
            a_coeff = 1.0
            b_coeff = 1.0

        # Decision variable: velocity
        v = cp.Variable(3)

        # Cost function: ||v - v_ref||² (Equation 35)
        cost = cp.sum_squares(v[0] - v_ref[0])  # vx

        if mode == 'H' or mode == 'V':
            if mode == 'H':
                cost += a_coeff * cp.sum_squares(v[1] - v_ref[1])  # vy
            if mode == 'V':
                cost += b_coeff * cp.sum_squares(v[2] - v_ref[2])  # vz
        else:
            cost += cp.sum_squares(v[1] - v_ref[1])
            cost += cp.sum_squares(v[2] - v_ref[2])

        # CBF constraint: h_dot >= -k*h (Equation 34)
        if mode == 'H':
            delta = vehicle_pos[:2] - obstacle_pos[:2]
            constraint_expr = 2 * (delta[0] * v[0] + delta[1] * v[1])
        elif mode == 'V':
            delta_x = vehicle_pos[0] - obstacle_pos[0]
            delta_z = vehicle_pos[2] - obstacle_pos[2]
            constraint_expr = 2 * (delta_x * v[0] + delta_z * v[2])
        else:
            delta = vehicle_pos - obstacle_pos
            constraint_expr = 2 * cp.sum(cp.multiply(delta, v))

        constraints = [constraint_expr >= -self.k * h]

        # Velocity bounds
        constraints.append(v[0] >= 0)  # Forward only
        constraints.append(v[0] <= self.v_max)
        constraints.append(cp.abs(v[1]) <= self.v_max)
        constraints.append(cp.abs(v[2]) <= self.v_max)

        # Solve QP
        problem = cp.Problem(cp.Minimize(cost), constraints)

        try:
            problem.solve(solver=cp.ECOS, verbose=False)

            if problem.status == cp.OPTIMAL:
                return v.value
            else:
                # QP failed - return conservative velocity
                return self._simple_projection(v_ref, h, vehicle_pos, obstacle_pos, mode)

        except:
            # Solver error - use fallback
            return self._simple_projection(v_ref, h, vehicle_pos, obstacle_pos, mode)

    def _simple_projection(self,
                          v_ref: np.ndarray,
                          h: float,
                          vehicle_pos: np.ndarray,
                          obstacle_pos: np.ndarray,
                          mode: str) -> np.ndarray:
        """
        Simple projection fallback when cvxpy is not available
        """
        # Direction away from obstacle
        if mode == 'H':
            delta = vehicle_pos[:2] - obstacle_pos[:2]
        elif mode == 'V':
            delta = vehicle_pos[[0, 2]] - obstacle_pos[[0, 2]]
        else:
            delta = vehicle_pos - obstacle_pos

        delta_norm = np.linalg.norm(delta)

        if delta_norm < 1e-6:
            # Too close - stop
            return np.zeros(3)

        # Project reference velocity away from obstacle
        delta_normalized = delta / delta_norm

        # Check if reference is moving toward obstacle
        if mode == 'H':
            v_toward = np.dot(v_ref[:2], delta_normalized)
        elif mode == 'V':
            v_toward = np.dot(v_ref[[0, 2]], delta_normalized)
        else:
            v_toward = np.dot(v_ref, delta_normalized)

        if v_toward < 0:
            # Moving toward obstacle - reduce or reverse
            v_safe = v_ref.copy()

            if h < 0.5:  # Very close
                # Stop or move away
                if mode == 'H':
                    v_safe[:2] = delta_normalized * 0.1
                elif mode == 'V':
                    v_safe[[0, 2]] = delta_normalized * 0.1
                else:
                    v_safe = delta_normalized * 0.1
            else:
                # Reduce speed
                scale = min(1.0, h / 2.0)
                v_safe = v_ref * scale

            return v_safe

        return v_ref