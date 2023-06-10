#!/usr/bin/env python3
# CircuitPython HTTP API Loader

# Operations:
# upload (filename) - upload a file to the board
# list - list files on the board
# download (filename) - download a file from the board
# delete (filename) - delete a file from the board
# list-devices - list all devices on the network

# -d (device) - specify a device to use (by ID)
# -u (url) - specify a URL to use (by IP address or hostname)

import argparse
from argparse import Namespace
import base64
from debugpy import connect
from numpy import save
import requests
from pathlib import Path
import sys
import os
import json
import threading
import time
import queue
from requests.exceptions import ConnectionError
from getpass import getpass

programDir = Path(sys.argv[0]).resolve().parent
configFile = programDir.joinpath('config.json')
defaultUrl = 'http://circuitpython.local'
config = {}
configChanged = False
loadingCursor = ['|', '/', '-', '\\']

class Device(threading.Thread):
    def __init__(self, args : Namespace):
        super().__init__()
        self.args = args
        self.baseUrl = args.url
        self.id = args.device
        self.device = None
        self.files = None
        self.connected = False
        self.running = True
        self.cmdQueue = queue.Queue()
        self.outputQueue = queue.Queue()
        self.passwordQueue = queue.Queue()
        self.error = False
        self.others = []
        
    def task(self, msg):
        self.outputQueue.put({'task': msg})
        
    def log(self, msg):
        self.outputQueue.put({'log': msg})
        
    def result(self, msg):
        self.outputQueue.put({'result': msg})

    def connect(self):
        global config, configChanged
        if self.connected:
            self.log('Already connected to ' + self.baseUrl)
            return
        if self.baseUrl == defaultUrl and self.id in config['devices']:
            self.baseUrl = config['devices'][self.id]['url']

        self.task('Connecting to ' + self.baseUrl + '...')
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'CircuitPython Web Loader'})
        # The version.json file contains properties about the current board.
        r = self.session.get(self.baseUrl + '/cp/version.json')
        if r.status_code != 200:
            self.result('Failed to connect to ' + self.baseUrl)
            self.error = True
            return
        self.props = r.json()
        # If the device ID is not specified, use the ID from the host name.
        if not self.id:
            self.id = self.props['hostname'][4:]
        # If the device ID is not in the config file, add it.
        if self.id not in config['devices']:
            config['devices'][self.id] = {'url': f'http://{self.props["hostname"]}.local', 'password': ''}
            configChanged = True
        if self.baseUrl == defaultUrl:
            self.baseUrl = config['devices'][self.id]['url']
        self.connected = True
        self.error = False
        self.result('Okay')
        if 'password' not in config['devices'][self.id] or config['devices'][self.id]['password'] == '':
            self.task(f'Enter password for {self.props["board_name"]} [{self.id}]: ')
            password = self.passwordQueue.get()
            config['devices'][self.id]['password'] = password
            configChanged = True
        self.session.headers.update({'Authorization': f'Basic {config["devices"][self.id]["password"]}'})
        self.log(f'Board: {self.props["board_name"]}')
        self.log(f'Firmware: {self.props["version"]}')
        self.log(f'IP Address: {self.props["ip"]}')

        self.task('Looking for other devices...')
        r = self.session.get(self.baseUrl + '/cp/devices.json')
        if r.status_code != 200:
            self.result('Failed to find other devices')
            self.error = True
            return
        self.result('Okay')
        self.others = r.json()['devices']
        for device in self.others:
            self.log(f'Found: {device["instance_name"]} [{device["hostname"][4:]}]')
       
    def disconnect(self):
        if not self.connected:
            return
        self.connected = False
        self.log('Disconnected from ' + self.baseUrl)
        
    def upload(self, filename):
        self.task('Uploading ' + filename + '...')
        with open(filename, 'rb') as f:
            try:
                self.session.put(self.baseUrl + '/fs/' + str(Path(filename).name), headers={'Content-Type': 'application/octet-stream'}, data=f)
            except ConnectionError as e:
                self.result('Failed to upload ' + filename)
                print(e)
                self.log('Upload error. Try resetting the board.')
                self.error = True
            else:
                self.result('Okay')
            
    def listDevices(self):
        # Device a nice table of devices.
        self.log(f'\n{" Devices ":=^90}')
        self.log(f'{"Name":<30} {"ID":<10} {"IP Address":<20} {"URL":<30}')
        self.log(f'{"":-^90}')
        self.logDevice(self.id, self.props['board_name'], self.baseUrl + '/', self.props['ip'])
        for device in self.others:
            self.logDevice(device['hostname'][4:], device['instance_name'], f'http://{device["hostname"]}.local/', device['ip'])
        self.log(f'{"":=^90}')
            
    def logDevice(self, id, name, url, ip):
        self.log(f'{name:<30} {id:<10} {ip:<20} {url}')

    def listFiles(self, dirname):
        self.task('Listing files...')
        r = self.session.get(f'{self.baseUrl}/fs/{dirname}')
        self.files = r.json()
        self.result('Okay')
        self.log(self.files)
        
    def download(self, filename):
        self.task('Downloading ' + filename + '...')
        r = self.session.get(self.baseUrl + '/fs/' + filename)
        if r.status_code != 200:
            self.result('Failed to download ' + filename)
            self.error = True
            return
        with open(filename, 'wb') as f:
            f.write(r.content)
        self.result('Okay')
        
    def delete(self, filename):
        self.task('Deleting ' + filename + '...')
        r = self.session.delete(self.baseUrl + '/fs/' + filename)
        if r.status_code != 200:
            self.result('Failed to delete ' + filename)
            self.error = True
            return
        self.result('Okay')
        
    def move(self, filename, newFilename):
        self.task('Moving ' + filename + '...')
        r = self.session.request('MOVE', self.baseUrl + '/fs/' + filename, headers={'Destination': newFilename})
        if r.status_code != 200:
            self.result('Failed to move ' + filename)
            self.error = True
            return
        self.result('Okay')
        
    def abortQueue(self):
        while not self.cmdQueue.empty():
            self.cmdQueue.get(block=False)
            self.cmdQueue.task_done()

    def run(self):
        while self.running:
            cmd = self.cmdQueue.get()
            if cmd[0] == 'connect':
                self.connect()
            elif cmd[0] == 'disconnect':
                self.disconnect()
            elif cmd[0] == 'quit':
                self.running = False
            elif not self.connected:
                print('Not connected to device')
            elif cmd[0] == 'upload':
                self.upload(cmd[1])
            elif cmd[0] == 'list':
                self.listFiles()
            elif cmd[0] == 'download':
                self.download(cmd[1])
            elif cmd[0] == 'delete':
                self.delete(cmd[1])
            elif cmd[0] == 'list-devices':
                self.listDevices()
            else:
                self.log('Unknown command: ' + cmd[0])
                self.error = True

            if self.error:
                self.log('Failed.')
                self.abortQueue()
                self.running = False
            else:
                self.cmdQueue.task_done()
            time.sleep(0.1)
                
                
        

def newConfig() -> dict:
    return { 'devices': {} }
        
def loadConfig() -> None:
    global config, configChanged
    if not configFile.exists():
        configFile.touch()
        config = newConfig()
        configChanged = True
        saveConfig()
    else:
        with open(configFile) as f:
            config = json.load(f)
            
def saveConfig() -> None:
    global config, configChanged
    if configChanged:
        with open(configFile, 'w') as f:
            json.dump(config, f, indent=2)
        configChanged = False
    
def loadArgs() -> Namespace:
    parser = argparse.ArgumentParser(description='CircuitPython HTTP API Loader')
    parser.add_argument('operation', help='operation to perform', choices=['list-devices', 'upload', 'list', 'download', 'delete'])
    parser.add_argument('filename', nargs='?', default='', help='filename to upload, download, or delete')
    parser.add_argument('-u', '--url', help='URL of the board', default='http://circuitpython.local')
    parser.add_argument('-d', '--device', help='ID of the device to use')
    return parser.parse_args()

def upload(args: Namespace):
    with open(args.filename, 'rb') as f:
        r = requests.put(args.url + '/fs/' + str(Path(args.filename).parent), headers={'Content-Type': 'application/octet-stream'}, data=f)

def commandWait(dev: Device, loading=False) -> None:
    index = 0
    if not dev.connected:
        time.sleep(0.2)
        return
    print(' ', end='')
    while dev.outputQueue.empty() and dev.connected:
        if loading:
            print('\b' + loadingCursor[index], end='')
            index = (index + 1) % len(loadingCursor)
        time.sleep(0.2)
    print('\b', end='')



def showOutput(dev: Device):
    while True:
        waitTask = False
        passwordTask = False
        while not dev.outputQueue.empty():
            waitTask = False
            passwordTask = False
            output = dev.outputQueue.get()
            if 'task' in output:
                print(output['task'], end='')
                if output['task'].endswith('...'):
                    waitTask = True
                elif output['task'].startswith('Enter password'):
                    passwordTask = True
            elif 'log' in output:
                print(output['log'])
            elif 'result' in output:
                print(output['result'])
            else:
                print(output)
            dev.outputQueue.task_done()
        if dev.running:
            if passwordTask:
                # The HTTP login expects ':' following by a password, all encoded in base64.
                password = getpass(prompt='')
                b64pass = base64.b64encode(b':' + password.encode('utf-8')).decode('utf-8')
                dev.passwordQueue.put(b64pass)
            commandWait(dev, loading=waitTask)
        else:
            break

def main() -> None:
    loadConfig()
    args = loadArgs()
    dev = Device(args)
    dev.start()
    dev.cmdQueue.put(['connect'])
    dev.cmdQueue.put([args.operation, args.filename])
    dev.cmdQueue.put(['disconnect'])
    dev.cmdQueue.put(['quit'])
    showOutput(dev)
    saveConfig()
    
if __name__ == '__main__':
    main()
    


