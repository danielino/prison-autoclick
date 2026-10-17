# AutoPrison

Autoclick y grabador de secuencias para **Prison Legacy**, inspirado en el AutoPrisión DX de MoleDJ para La Prisión. Reescrito desde cero.
Programa externo: solo simula ratón y teclado (SendInput) y lee pixeles de la pantalla. No abre, no lee ni modifica el proceso del juego. Proyecto no oficial, sin relación con los responsables del juego.

> Úsalo bajo tu responsabilidad. Comprueba las normas actuales del juego sobre automatización: la autorización del AutoPrisión original se refería a La Prisión, no a Prison Legacy.

## Uso

Descarga `AutoPrison.exe` de [Releases](../../releases), ejecútalo (con tu usuario normal, igual que el juego, no como administrador) y entra al juego. Con el juego en primer plano, **TAB** abre el menú:

| Tecla | Acción |
|---|---|
| 1 | Autoclick en la posición del cursor |
| 2 + 1-9 | Grabar secuencia en ese hueco |
| 3 + 1-9 | Reproducir secuencia (en bucle) |
| 4 | Velocidad (1 sube, 2 baja, 0 sale) |
| 5 | Autopelea simple (`/repetir` cada pocos segundos) |
| 6 | Autopelea doble turno: alterna las secuencias 8 y 9 |
| 0 | Cerrar el menú |

**TAB** vuelve a pulsarse para parar o para terminar de grabar. Todo se detiene si el juego pierde el foco.

### Esperar a una ventana al grabar

Mientras grabas, justo después del clic que abre una ventana:

- **F9**: ventana de diálogo en el centro (p. ej. "MÁQUINA: ¿Echas el dinero?").
- **F10**: menú junto al cursor.

Al reproducir, el programa espera a que esa zona cambie antes de seguir. Si no aparece en 3 s, repite el clic una vez.

## Configuración

`autoprison_data.json`, junto al exe (o en `%APPDATA%\AutoPrison` si la carpeta no es escribible): `hotkey` (`TAB`, `F8`...), `speed`, `jitter` (variación aleatoria de tiempos, 0.2 = ±20 %), `repeat_command`, etc. Las secuencias se guardan al instante. `autoprison.log` ayuda a diagnosticar.

## Compilar

```
python autoprison.py
pip install pyinstaller && pyinstaller --onefile --console --name AutoPrison autoprison.py
```

Las releases las genera GitHub Actions al subir una etiqueta `v*` (`git tag v1.0.0 && git push --tags`), junto con el hash SHA-256 del exe.

## Antivirus

Los exe de PyInstaller que simulan entrada a veces dan falsos positivos. Por eso el exe se construye en público desde este código; compara el SHA-256 de la release con el de tu descarga.
