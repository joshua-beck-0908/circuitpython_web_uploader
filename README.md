# CircuitPython Web Uploader
A tool to upload to CircuitPython boards over LAN.

This is useful if you want to be able to use any IDE you want an upload your code wirelessly to your CircuitPython board, even ESP32 and ESP32C3 boards that do not have a PyDrive.

**NOTE: You must have CircuitPython 8.0 or higher and have your board connected to WiFi for this to work.**

See this guide from Adafruit to have your device automatically connect: https://learn.adafruit.com/getting-started-with-web-workflow-using-the-code-editor

## Usage
```cpwebloader.py [-d device_id] [-u device_url] operation files```

Possible operations:
 * `list` - List files on the board
 * `upload` - Upload a file to the board.
 * `download` - Download a file from the board.
 * `delete` - Delete a file from the board.
 * `list` - List files in a board directory.
 * `list-devices` - Lists usable CircuitPython devices on the local network.
 
e.g. `cpwebloader.py -d 123456 upload main.py` will upload the file `main.py` to the device with id `123456`.
 
The device id is an optional argument to ensure your code uploads to the correct device if you have several on the network. If you don't specify a device id, the first device found will be used.

A config file `config.json` will be created in the current directory the first time you run the script. This file will remember previously connected devices and their URLs.

You may want to copy the script to your PATH so you can run it from anywhere.

The code currently in the `.vscode/launch.json` file simple uploads the file `main.py` to the device with VSCode.
You can change this to upload any file you want.

If you are writing CircuitPython code with VSCode you should take a look at joedevivo's excellent [CircuitPython VSCode extension](https://marketplace.visualstudio.com/items?itemName=joedevivo.vscode-circuitpython) , this will provide the stubs for CircuitPython modules and allow you to lint your code.
