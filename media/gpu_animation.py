import os
from array import array

from PySide6.QtCore import QCoreApplication, QSize, QThread, Qt
from PySide6.QtGui import QOpenGLContext, QOffscreenSurface, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
)


_VERTEX_SHADER = """
attribute vec2 position;
varying vec2 coordinates;
void main() {
    coordinates = position * 0.5 + 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER = """
#ifdef GL_ES
precision highp float;
#endif
varying vec2 coordinates;
uniform float phase;
uniform float noiseScale;
uniform vec2 direction;
uniform vec3 colorA;
uniform vec3 colorB;
uniform bool transparentB;
uniform vec2 resolution;

float hash(vec2 cell) {
    return fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 point) {
    vec2 cell = floor(point);
    vec2 fraction = fract(point);
    fraction = fraction * fraction * (3.0 - 2.0 * fraction);
    float top = mix(hash(cell), hash(cell + vec2(1.0, 0.0)), fraction.x);
    float bottom = mix(hash(cell + vec2(0.0, 1.0)), hash(cell + vec2(1.0, 1.0)), fraction.x);
    return mix(top, bottom, fraction.y);
}

void main() {
    vec2 samplePoint = coordinates * resolution * noiseScale + phase * direction;
    float directionLength = length(direction);
    if (directionLength > 0.0) {
        samplePoint += phase * (direction / directionLength - direction);
    }
    float value = noise(samplePoint);
    vec3 color = mix(colorA, colorB, value);
    float alpha = transparentB ? 1.0 - value : 1.0;
    gl_FragColor = vec4(color, alpha);
}
"""


class GpuAnimationRenderer:
    """Optional offscreen shader renderer for procedural animation frames."""

    def __init__(self, width: int, height: int, render_scale: float):
        self.width = width
        self.height = height
        self.render_scale = render_scale
        self.render_width = max(16, round(width * render_scale))
        self.render_height = max(16, round(height * render_scale))
        self.context = None
        self.surface = None
        self.framebuffer = None
        self.program = None
        self.functions = None
        self.vertex_buffer = None
        self.available = False
        self._initialization_attempted = False

    def initialize(self) -> bool:
        if self._initialization_attempted:
            return self.available
        self._initialization_attempted = True
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return False
        application = QCoreApplication.instance()
        if application is None or QThread.currentThread() != application.thread():
            return False
        try:
            self.context = QOpenGLContext()
            self.context.setFormat(QSurfaceFormat.defaultFormat())
            if not self.context.create():
                return False

            self.surface = QOffscreenSurface()
            self.surface.setFormat(self.context.format())
            self.surface.create()
            if not self.surface.isValid() or not self.context.makeCurrent(self.surface):
                return False

            framebuffer_format = QOpenGLFramebufferObjectFormat()
            framebuffer_format.setAttachment(
                QOpenGLFramebufferObject.Attachment.CombinedDepthStencil
            )
            self.framebuffer = QOpenGLFramebufferObject(
                QSize(self.render_width, self.render_height),
                framebuffer_format,
            )
            self.program = QOpenGLShaderProgram()
            if not self.program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX_SHADER
            ):
                return False
            if not self.program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT_SHADER
            ):
                return False
            self.program.bindAttributeLocation("position", 0)
            if not self.program.link():
                return False
            self.functions = self.context.functions()
            self.vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not self.vertex_buffer.create():
                return False
            self.vertex_buffer.bind()
            self.vertex_buffer.allocate(
                array("f", (-1.0, -1.0, 3.0, -1.0, -1.0, 3.0)).tobytes()
            )
            self.vertex_buffer.release()
            self.available = True
            return True
        except Exception:
            self.available = False
            return False
        finally:
            if self.context is not None and self.surface is not None:
                self.context.doneCurrent()

    def render(
        self,
        phase: float,
        noise_scale: float,
        direction: tuple[float, float],
        color_a: tuple[int, int, int],
        color_b: tuple[int, int, int],
        transparent_b: bool,
    ):
        if not self.available:
            return None
        if not self.context.makeCurrent(self.surface):
            return None
        try:
            self.framebuffer.bind()
            self.functions.glViewport(0, 0, self.render_width, self.render_height)
            self.functions.glClearColor(0.0, 0.0, 0.0, 0.0)
            self.functions.glClear(self.functions.GL_COLOR_BUFFER_BIT)

            self.program.bind()
            self.program.setUniformValue("phase", phase)
            self.program.setUniformValue(
                "noiseScale",
                max(0.0001, noise_scale / self.render_scale),
            )
            self.program.setUniformValue(
                "resolution", self.render_width, self.render_height
            )
            self.program.setUniformValue("direction", direction[0], direction[1])
            self.program.setUniformValue(
                "colorA",
                color_a[0] / 255.0,
                color_a[1] / 255.0,
                color_a[2] / 255.0,
            )
            self.program.setUniformValue(
                "colorB",
                color_b[0] / 255.0,
                color_b[1] / 255.0,
                color_b[2] / 255.0,
            )
            self.program.setUniformValue("transparentB", transparent_b)

            self.vertex_buffer.bind()
            self.program.enableAttributeArray(0)
            self.program.setAttributeBuffer(
                0, self.functions.GL_FLOAT, 0, 2, 0
            )
            self.functions.glDrawArrays(self.functions.GL_TRIANGLES, 0, 3)
            self.program.disableAttributeArray(0)
            self.vertex_buffer.release()
            self.program.release()
            image = self.framebuffer.toImage()
            if self.render_scale < 1.0:
                image = image.scaled(
                    self.width,
                    self.height,
                    aspectMode=Qt.AspectRatioMode.IgnoreAspectRatio,
                    mode=Qt.TransformationMode.FastTransformation,
                )
            return image
        except Exception:
            self.available = False
            return None
        finally:
            self.framebuffer.release()
            self.context.doneCurrent()

    def close(self):
        if self.context is not None and self.surface is not None:
            self.context.makeCurrent(self.surface)
            if self.vertex_buffer is not None:
                self.vertex_buffer.destroy()
                self.vertex_buffer = None
            self.framebuffer = None
            self.program = None
            self.context.doneCurrent()
        self.available = False
        if self.surface is not None:
            self.surface.destroy()
            self.surface = None
        self.context = None
