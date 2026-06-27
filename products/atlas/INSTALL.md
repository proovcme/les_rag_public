# АТЛАС Install

## macOS / Linux

```bash
unzip atlas-standalone.zip
cd atlas-standalone
./serve.sh 8095
```

Open:

```text
http://127.0.0.1:8095/
```

## Windows PowerShell

```powershell
Expand-Archive .\atlas-standalone.zip -DestinationPath .
cd .\atlas-standalone
powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095
```

Open:

```text
http://127.0.0.1:8095/
```

For LAN users, run on the server and open:

```text
http://SERVER:8095/
```

Do not open `index.html` directly in production. Browser security rules can block WASM, workers or local model files. Use the bundled server scripts.

