import os
from array import array

from PySide6.QtCore import QCoreApplication, QSize, QThread, Qt
from PySide6.QtGui import QImage, QOpenGLContext, QOffscreenSurface, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
)

_VERTEX = """
attribute vec2 position;
uniform vec4 rectangle;
varying vec2 coordinates;
void main() {
    coordinates = position;
    vec2 point = rectangle.xy + position * rectangle.zw;
    gl_Position = vec4(point.x * 2.0 - 1.0, 1.0 - point.y * 2.0, 0.0, 1.0);
}
"""

_FRAGMENT = """
#ifdef GL_ES
precision highp float;
#endif
varying vec2 coordinates;
uniform sampler2D imageTexture;
uniform bool animated;
uniform float phase;
uniform float noiseScale;
uniform vec2 resolution;
uniform vec2 direction;
uniform vec3 colorA;
uniform vec3 colorB;
uniform bool transparentB;

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
    if (!animated) {
        gl_FragColor = texture2D(imageTexture, coordinates);
        return;
    }
    vec2 unitDirection = direction;
    float directionLength = length(unitDirection);
    if (directionLength > 0.0) unitDirection /= directionLength;
    float value = noise(coordinates * resolution * noiseScale + phase * unitDirection);
    vec3 color = mix(colorA, colorB, value);
    float alpha = transparentB ? 1.0 - value : 1.0;
    gl_FragColor = vec4(color, alpha);
}
"""


class GpuCompositionRenderer:
    """Composes image and procedural-animation layers in one GPU pass."""

    def __init__(self):
        self.context = None
        self.surface = None
        self.framebuffer = None
        self.program = None
        self.vertex_buffer = None
        self.functions = None
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
            self.program = QOpenGLShaderProgram()
            if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, _VERTEX):
                return False
            if not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, _FRAGMENT):
                return False
            self.program.bindAttributeLocation("position", 0)
            if not self.program.link():
                return False
            self.functions = self.context.functions()
            self.vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not self.vertex_buffer.create():
                return False
            self.vertex_buffer.bind()
            self.vertex_buffer.allocate(array("f", (0.0, 0.0, 1.0, 0.0, 0.0, 1.0)).tobytes())
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
        states,
        size: QSize,
        background,
        output_scale: float = 1.0,
    ) -> QImage | None:
        if not self.available or not self.context.makeCurrent(self.surface):
            return None
        textures = []
        try:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            self.framebuffer = QOpenGLFramebufferObject(size, fmt)
            self.framebuffer.bind()
            self.functions.glViewport(0, 0, size.width(), size.height())
            self.functions.glClearColor(background.redF(), background.greenF(), background.blueF(), 1.0)
            self.functions.glClear(self.functions.GL_COLOR_BUFFER_BIT)
            self.functions.glEnable(self.functions.GL_BLEND)
            self.functions.glBlendFunc(
                self.functions.GL_SRC_ALPHA,
                self.functions.GL_ONE_MINUS_SRC_ALPHA,
            )
            self.program.bind()
            self.vertex_buffer.bind()
            self.program.enableAttributeArray(0)
            self.program.setAttributeBuffer(0, self.functions.GL_FLOAT, 0, 2, 0)
            for state in states:
                animation = getattr(state, "animation", None)
                texture = None
                if animation is None:
                    if state.image.isNull():
                        continue
                    texture = QOpenGLTexture(state.image)
                    texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
                    texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
                    texture.bind()
                    textures.append(texture)
                self.program.setUniformValue("animated", animation is not None)
                self.program.setUniformValue(
                    "rectangle",
                    *self._rectangle(state, size, animation, output_scale),
                )
                if animation is not None:
                    self.program.setUniformValue("phase", animation["phase"])
                    self.program.setUniformValue("noiseScale", animation["noise_scale"])
                    self.program.setUniformValue("resolution", animation["width"], animation["height"])
                    self.program.setUniformValue("direction", *animation["direction"])
                    self.program.setUniformValue("colorA", *animation["color_a"])
                    self.program.setUniformValue("colorB", *animation["color_b"])
                    self.program.setUniformValue("transparentB", animation["transparent_b"])
                self.functions.glDrawArrays(self.functions.GL_TRIANGLES, 0, 3)
                if texture is not None:
                    texture.release()
            self.program.disableAttributeArray(0)
            self.vertex_buffer.release()
            self.program.release()
            self.functions.glDisable(self.functions.GL_BLEND)
            return self.framebuffer.toImage()
        except Exception:
            self.available = False
            return None
        finally:
            for texture in textures:
                texture.destroy()
            self.framebuffer = None
            self.context.doneCurrent()

    @staticmethod
    def _rectangle(state, size, animation, output_scale):
        image = state.image
        width = animation["width"] if animation is not None else image.width()
        height = animation["height"] if animation is not None else image.height()
        scaled_width = width * state.scale[0] * output_scale / size.width()
        scaled_height = height * state.scale[1] * output_scale / size.height()
        return (
            state.offset.x() * output_scale / size.width(),
            state.offset.y() * output_scale / size.height(),
            scaled_width,
            scaled_height,
        )

    def close(self):
        if self.context is not None and self.surface is not None:
            self.context.makeCurrent(self.surface)
            if self.vertex_buffer is not None:
                self.vertex_buffer.destroy()
            self.program = None
            self.framebuffer = None
            self.context.doneCurrent()
            self.surface.destroy()
        self.available = False
        self.context = None
        self.surface = None
