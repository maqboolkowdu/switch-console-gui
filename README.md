# Switch Console GUI

Field laptop tool for Cisco IOS/IOS-XE and HPE/Aruba switches (ProVision, Comware, Aruba CX).

A browser page talks to the device over:

- USB / RS-232 console (Web Serial in Chrome or Edge)
- SSH or Telnet through the local companion script

It draws a faceplate, health pills, and a CDP/LLDP link-node map, and includes a command library with Cisco and HPE equivalents.

This is a local helper. It is not HPE Aruba Central or Cisco DNA/Catalyst Center.

## Files

| File | Purpose |
|---|---|
| `switch-console-gui.html` | UI, parsers, topology, profiles, tutorial |
| `switch-console-server.py` | Serves the page and bridges SSH/Telnet |

## Requirements

- Google Chrome or Microsoft Edge
- Python 3.10+
- For SSH: `pip install paramiko`
- USB-serial driver if you use a console cable (FTDI, CP210x, Prolific)

## Run

```bash
pip install paramiko
python switch-console-server.py
```

Open http://127.0.0.1:8080/switch-console-gui.html

Do not open the HTML as `file://` if you need Web Serial or SSH/Telnet.

## First connection

1. Choose **Serial**, **SSH**, or **Telnet**.
2. Set platform to **Auto-detect after poll**, or pick Cisco / ProVision / Comware / Aruba CX.
3. Connect. On console, wait for `Username:` / `Password:` and send the **account name**, not a `show` command.
4. Reach `#`, then **Poll inventory**.
5. Save a **device profile** so the switch appears in the menu next time.

Typical serial settings: 9600 8-N-1 (try 115200 if the banner is garbage).

## 5400R / stacked ProVision

On a 5406Rzl2 and similar chassis the console often shows a full-screen banner and `Username:` at the bottom. Stack members print `Press any key to connect to the commander` after a failed login. Log in on the commander before polling.

## License

MIT
