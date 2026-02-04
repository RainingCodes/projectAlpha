"""
SCG: Spatial Context Generator
Maintains short-term memory of obstacles for partial observability handling
Based on EROAS paper Section III-C2
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ObstaclePoint:
    """Single obstacle point in 3D space"""
    x: float
    y: float
    z: float
    timestamp: float


class SCG:
    """
    Spatial Context Generator

    Maintains a radius-based memory of obstacle points to handle
    partial observability when obstacles leave the sonar FOV
    """

    def __init__(self, memory_radius: float = 15.0):
        """
        Initialize SCG

        Args:
            memory_radius: Radius of obstacle memory ball in meters
        """
        self.memory_radius = memory_radius
        self.obstacle_memory: List[ObstaclePoint] = []

    def update(self,
               new_points: np.ndarray,
               vehicle_position: np.ndarray,
               timestamp: float) -> None:
        """
        Update obstacle memory with new scan (Equation 29)

        Args:
            new_points: New obstacle points from sonar [N x 3]
            vehicle_position: Current vehicle position [x, y, z]
            timestamp: Current time
        """
        # Remove points outside memory radius
        self.obstacle_memory = [
            p for p in self.obstacle_memory
            if self._distance(
                np.array([p.x, p.y, p.z]),
                vehicle_position
            ) <= self.memory_radius
        ]

        # Add new points within memory radius
        for point in new_points:
            if self._distance(point, vehicle_position) <= self.memory_radius:
                self.obstacle_memory.append(
                    ObstaclePoint(
                        x=point[0],
                        y=point[1],
                        z=point[2],
                        timestamp=timestamp
                    )
                )

    def get_closest_obstacle(self,
                            vehicle_position: np.ndarray,
                            mode: str = 'H') -> Optional[np.ndarray]:
        """
        Get closest obstacle point for CBF (Equation 30)

        Args:
            vehicle_position: Current vehicle position [x, y, z]
            mode: 'H' for horizontal (XY), 'V' for vertical (XZ)

        Returns:
            Closest obstacle point coordinates, or None if no obstacles
        """
        if not self.obstacle_memory:
            return None

        # Get all points as array
        points = np.array([
            [p.x, p.y, p.z] for p in self.obstacle_memory
        ])

        if mode == 'H':
            # Horizontal: consider only XY plane
            vehicle_xy = vehicle_position[:2]
            points_xy = points[:, :2]
            distances = np.linalg.norm(points_xy - vehicle_xy, axis=1)
            closest_idx = np.argmin(distances)
            return points[closest_idx]

        elif mode == 'V':
            # Vertical: consider XZ plane
            vehicle_xz = vehicle_position[[0, 2]]
            points_xz = points[:, [0, 2]]
            distances = np.linalg.norm(points_xz - vehicle_xz, axis=1)
            closest_idx = np.argmin(distances)
            return points[closest_idx]

        else:
            # Full 3D
            distances = np.linalg.norm(points - vehicle_position, axis=1)
            closest_idx = np.argmin(distances)
            return points[closest_idx]

    def get_local_obstacles(self,
                           vehicle_position: np.ndarray) -> np.ndarray:
        """
        Get all obstacles in local memory (Equation 28)

        Args:
            vehicle_position: Current vehicle position

        Returns:
            Array of obstacle points [N x 3]
        """
        if not self.obstacle_memory:
            return np.array([]).reshape(0, 3)

        points = np.array([
            [p.x, p.y, p.z] for p in self.obstacle_memory
        ])

        # Filter by memory radius
        distances = np.linalg.norm(points - vehicle_position, axis=1)
        valid_mask = distances <= self.memory_radius

        return points[valid_mask]

    def clear(self):
        """Clear all obstacle memory"""
        self.obstacle_memory.clear()

    def get_memory_size(self) -> int:
        """Get number of points in memory"""
        return len(self.obstacle_memory)

    @staticmethod
    def _distance(p1: np.ndarray, p2: np.ndarray) -> float:
        """Calculate Euclidean distance"""
        return np.linalg.norm(p1 - p2)