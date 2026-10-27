from collections.abc import Mapping, Sequence


class Shader:
    shaderType: int
    code: str
    compiled: object | None


class VertexShader(Shader):
    def __init__(self, code: str) -> None: ...


class FragmentShader(Shader):
    def __init__(self, code: str) -> None: ...


class ShaderProgram:
    names: dict[str | None, ShaderProgram]
    name: str | None
    shaders: list[Shader]
    uniformData: dict[str, Sequence[float]]

    def __init__(
        self,
        name: str | None,
        shaders: Sequence[Shader],
        uniforms: Mapping[str, Sequence[float]] | None = None,
    ) -> None: ...

    def setUniformData(self, uniformName: str, data: Sequence[float] | None) -> None: ...

    def __setitem__(self, item: str, val: Sequence[float]) -> None: ...
