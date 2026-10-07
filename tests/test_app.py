from inventario import app
from inventario.nucleo import clonacion


def test_ayuda(capsys):
    assert app.main(["--ayuda"]) == 0
    assert "--clonacion" in capsys.readouterr().out


def test_clonacion_sin_conexion_devuelve_2(monkeypatch):
    def falla():
        raise RuntimeError("sin red")

    monkeypatch.setattr(clonacion, "abrir_conexion_scp", falla)
    assert clonacion.modo_clonacion(sin_ui=True) == 2
