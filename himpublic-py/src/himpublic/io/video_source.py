"""Video source abstraction - webcam, file, robot (placeholder)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BaseVideoSource(ABC):
    """Abstract video source. Subclasses: WebcamVideoSource, FileVideoSource, RobotVideoSource."""

    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return next frame as BGR numpy array, or None on end/error."""
        ...

    @abstractmethod
    def release(self) -> None:
        """Release resources."""
        ...


class WebcamVideoSource(BaseVideoSource):
    """Video from webcam by index."""

    def __init__(self, index: int = 0) -> None:
        self._index = index
        self._cap: cv2.VideoCapture | None = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            logger.error("WebcamVideoSource: failed to open webcam index=%s", index)
            self._cap = None
        else:
            logger.info("WebcamVideoSource: opened index=%s", index)

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            logger.debug("WebcamVideoSource: read failed or end of stream")
            return None
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.debug("WebcamVideoSource: released")


class FileVideoSource(BaseVideoSource):
    """Video from file path."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._cap: cv2.VideoCapture | None = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            logger.error("FileVideoSource: failed to open path=%s", path)
            self._cap = None
        else:
            logger.info("FileVideoSource: opened path=%s", path)

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            logger.debug("FileVideoSource: end of file")
            return None
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.debug("FileVideoSource: released")


class RobotVideoSource(BaseVideoSource):
    """Placeholder for robot camera. Raises NotImplementedError."""

    def read(self) -> np.ndarray | None:
        logger.debug("RobotVideoSource.read() called")
        raise NotImplementedError(
            "RobotVideoSource: robot camera not yet implemented. Use --io local --video webcam or --video file."
        )

    def release(self) -> None:
        logger.debug("RobotVideoSource.release()")
