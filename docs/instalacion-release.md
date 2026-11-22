**Windows.** Descarga `steam-families.exe` y haz doble clic. Windows puede avisar de que no está firmado: **Más información -> Ejecutar de todas formas**. Los datos se guardan junto al ejecutable.

**Linux.**

```
chmod +x steam-families-linux
./steam-families-linux --datos datos
```

**macOS** (Apple Silicon).

```
chmod +x steam-families-macos
./steam-families-macos --datos datos
```

Si Gatekeeper lo bloquea: clic derecho -> Abrir, o `xattr -d com.apple.quarantine steam-families-macos`.

En los tres casos se abre una página en el navegador: pega el token de Steam y pulsa **Actualizar**.
