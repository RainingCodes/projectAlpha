"""
SPD2C: Sonar Profile-guided Directional Decision Control
Implements gap finding, boundedness check, convergence analysis, and sonar pivoting
Based on EROAS paper Section III-C1
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SPD2COutput:
    """Output from SPD2C module"""
    vx_ref: float  # Reference forward velocity
    vy_ref: float  # Reference lateral velocity
    vz_ref: float  # Reference vertical velocity
    r_ref: float   # Reference yaw rate
    pivot_angle: Optional[float] = None  # Sonar pivot angle if needed
    mode: str = 'H'  # 'H' for horizontal, 'V' for vertical


class SPD2C:
    """
    Sonar Profile-guided Directional Decision Control

    Processes 2D FLS data to generate reactive navigation commands
    """

    def __init__(self, params: dict):
        """
        Initialize SPD2C

        Args:
            params: Dictionary containing:
                - num_beams: Number of sonar beams (default 512)
                - fov_horizontal: Horizontal FOV in radians (default 90 deg)
                - intensity_threshold: Obstacle detection threshold (default 15)
                - gap_length: Minimum gap length in beams (default 150)
                - convergence_threshold: Convexity threshold (default 0.02)
                - v_max: Maximum forward velocity
                - r_max: Maximum yaw rate
                - Kv, Kt, Kr: Control gains
        """
        self.num_beams = params.get('num_beams', 512)
        self.fov_h = params.get('fov_horizontal', np.deg2rad(90))
        self.intensity_thr = params.get('intensity_threshold', 15.0)
        self.gap_length = params.get('gap_length', 150)
        self.conv_thr = params.get('convergence_threshold', 0.02)

        # Control parameters
        self.v_max = params.get('v_max', 1.0)
        self.r_max = params.get('r_max', np.deg2rad(15))
        self.Kv = params.get('Kv', 0.35)
        self.Kt = params.get('Kt', 0.12)
        self.Kr = params.get('Kr', 0.175)

        # Beam width
        self.beam_width = self.fov_h / self.num_beams

    def process(self, sonar_intensities: np.ndarray,
                goal_bearing: float,
                current_heading: float) -> SPD2COutput:
        """
        Process sonar scan and generate reference commands

        Args:
            sonar_intensities: Array of beam intensities [num_beams]
            goal_bearing: Bearing to goal in radians (global frame)
            current_heading: Current vehicle heading in radians

        Returns:
            SPD2COutput with reference velocities and yaw rate
        """
        # Step 1: Gap Finding
        gap_beam = self._find_gap(sonar_intensities, goal_bearing, current_heading)

        if gap_beam is not None:
            # Gap found - navigate through it
            return self._navigate_gap(gap_beam, current_heading)

        # Step 2: Check for Boundedness
        boundedness = self._check_boundedness(sonar_intensities)

        if boundedness in ['BO', 'LUBO', 'RUBO']:
            # Obstacle is bounded - turn appropriately
            return self._navigate_bounded(boundedness, goal_bearing, current_heading)

        # Step 3: Check for Convergence (UBO case)
        is_convex = self._check_convergence(sonar_intensities)

        if is_convex:
            # Convex obstacle - turn toward goal side
            return self._navigate_convex(goal_bearing, current_heading)

        # Step 4: Sonar Pivoting needed (concave/wall)
        # For now, return horizontal turn command
        # TODO: Implement vertical pivot scan
        return self._navigate_pivot_needed(goal_bearing, current_heading)

    def _find_gap(self, intensities: np.ndarray,
                  goal_bearing: float,
                  current_heading: float) -> Optional[int]:
        """
        Find feasible gap in sonar scan

        Returns:
            Beam index of gap center, or None if no gap found
        """
        # Identify obstacle-free beams (Equation 7)
        free_beams = intensities < self.intensity_thr

        if np.sum(free_beams) < self.gap_length:
            return None

        # Find continuous gaps of length L (Equation 8-9)
        gaps = []
        for i in range(len(free_beams) - self.gap_length + 1):
            if np.all(free_beams[i:i+self.gap_length]):
                mid_beam = i + self.gap_length // 2
                gaps.append(mid_beam)

        if not gaps:
            return None

        # Find gap closest to goal direction (Equation 11-13)
        goal_angle_rel = self._normalize_angle(goal_bearing - current_heading)
        target_beam = self._angle_to_beam(goal_angle_rel)
        target_beam = np.clip(target_beam, 0, self.num_beams - 1)

        # Choose gap closest to target
        gaps_array = np.array(gaps)
        closest_idx = np.argmin(np.abs(gaps_array - target_beam))

        return gaps[closest_idx]

    def _check_boundedness(self, intensities: np.ndarray) -> str:
        """
        Check if obstacle is bounded (Equation 14)

        Returns:
            'BO', 'LUBO', 'RUBO', or 'UBO'
        """
        obstacle_beams = intensities >= self.intensity_thr

        if not np.any(obstacle_beams):
            return 'BO'  # No obstacle

        obstacle_indices = np.where(obstacle_beams)[0]
        i_min = obstacle_indices[0]
        i_max = obstacle_indices[-1]

        left_bounded = i_min > 0
        right_bounded = i_max < self.num_beams - 1

        if left_bounded and right_bounded:
            return 'BO'  # Bounded on both sides
        elif not left_bounded and right_bounded:
            return 'LUBO'  # Left unbounded
        elif left_bounded and not right_bounded:
            return 'RUBO'  # Right unbounded
        else:
            return 'UBO'  # Unbounded on both sides

    def _check_convergence(self, intensities: np.ndarray) -> bool:
        """
        Check if UBO obstacle is convex (converging) (Equation 15)

        Returns:
            True if convex (converging), False if concave/wall
        """
        obstacle_beams = intensities >= self.intensity_thr
        if not np.any(obstacle_beams):
            return False

        # Get obstacle beam indices and ranges
        obstacle_indices = np.where(obstacle_beams)[0]

        # Simple approximation: fit polynomial to beam pattern
        # In full implementation, would transform to Cartesian and fit
        x = obstacle_indices.astype(float)
        y = intensities[obstacle_indices]

        if len(x) < 3:
            return False

        # Fit quadratic: a*x^2 + b*x + c
        try:
            coeffs = np.polyfit(x, y, 2)
            a = coeffs[0]

            # If a >= threshold, obstacle is converging (convex)
            return a >= self.conv_thr
        except:
            return False

    def _navigate_gap(self, gap_beam: int, heading: float) -> SPD2COutput:
        """Navigate through identified gap"""
        # Calculate desired heading
        psi_R = self._beam_to_angle(gap_beam)

        # Velocity and yaw rate (Equations 24, 26, 27)
        vx_ref = self.Kv * (self.fov_h/2 - abs(psi_R))
        vx_ref = np.clip(vx_ref, 0, self.v_max)

        r_ref = self.Kt * psi_R
        r_ref = np.clip(r_ref, -self.r_max, self.r_max)

        return SPD2COutput(
            vx_ref=vx_ref,
            vy_ref=0.0,
            vz_ref=0.0,
            r_ref=r_ref,
            mode='H'
        )

    def _navigate_bounded(self, boundedness: str,
                         goal_bearing: float,
                         heading: float) -> SPD2COutput:
        """Navigate around bounded obstacle"""
        goal_angle_rel = self._normalize_angle(goal_bearing - heading)

        # Decide turn direction
        if boundedness == 'LUBO':
            turn_direction = 1.0  # Turn right
        elif boundedness == 'RUBO':
            turn_direction = -1.0  # Turn left
        else:  # BO
            turn_direction = np.sign(goal_angle_rel)

        r_ref = turn_direction * self.r_max * 0.5

        return SPD2COutput(
            vx_ref=self.v_max * 0.3,  # Slow forward
            vy_ref=0.0,
            vz_ref=0.0,
            r_ref=r_ref,
            mode='H'
        )

    def _navigate_convex(self, goal_bearing: float,
                        heading: float) -> SPD2COutput:
        """Navigate around convex (converging) obstacle"""
        goal_angle_rel = self._normalize_angle(goal_bearing - heading)

        r_ref = self.Kt * goal_angle_rel
        r_ref = np.clip(r_ref, -self.r_max, self.r_max)

        return SPD2COutput(
            vx_ref=self.v_max * 0.5,
            vy_ref=0.0,
            vz_ref=0.0,
            r_ref=r_ref,
            mode='H'
        )

    def _navigate_pivot_needed(self, goal_bearing: float,
                              heading: float) -> SPD2COutput:
        """Handle case where vertical pivot is needed"""
        # For now, turn left and re-evaluate
        # TODO: Implement vertical pivot scan

        return SPD2COutput(
            vx_ref=self.v_max * 0.2,
            vy_ref=0.0,
            vz_ref=0.0,
            r_ref=-self.r_max * 0.3,  # Turn left
            mode='H',
            pivot_angle=None  # Will implement pivoting later
        )

    def _angle_to_beam(self, angle: float) -> int:
        """Convert angle to beam index"""
        # Angle range: [-fov_h/2, fov_h/2]
        # Beam range: [0, num_beams-1]
        normalized = (angle + self.fov_h/2) / self.fov_h
        beam = int(normalized * self.num_beams)
        return np.clip(beam, 0, self.num_beams - 1)

    def _beam_to_angle(self, beam: int) -> float:
        """Convert beam index to angle"""
        normalized = beam / self.num_beams
        angle = normalized * self.fov_h - self.fov_h/2
        return angle

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]"""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle