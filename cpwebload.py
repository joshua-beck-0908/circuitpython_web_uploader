#!/usr/bin/python3
# CircuitPython HTTP API Loader

# Operations:
# upload (filename) - upload a file to the board
# list - list files on the board
# download (filename) - download a file from the board
# delete (filename) - delete a file from the board

# -d (device) - specify a device to use (by ID)
# -u (url) - specify a URL to use (by IP address or hostname)

import argparse
from argparse import Namespace
from debugpy import connect
import requests
from pathlib import Path
import sys
import os
import json
import threading
import time
import queue
from requests.exceptions import ConnectionError

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
        self.error = False
        
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
        r = self.session.get(self.baseUrl + '/cp/version.json')
        if r.status_code != 200:
            self.result('Failed to connect to ' + self.baseUrl)
            self.error = True
            return
        self.props = r.json()
        if not self.id:
            self.id = self.props['UID']
        if self.baseUrl == defaultUrl:
            if self.id in config['devices']:
                self.baseUrl = config['devices'][self.id]['url']
            else:
                self.url = f'http://{self.props["hostname"]}.local'
        self.connected = True
        self.error = False
        self.result('Okay')
        self.session.headers.update({'Authorization': f'Basic {config["devices"][self.id]["password"]}'})
        self.log(f'Board: {self.props["board_name"]}')
        self.log(f'Firmware: {self.props["version"]}')
        self.log(f'IP Address: {self.props["ip"]}')
       
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
            
    def listFiles(self):
        self.task('Listing files...')
        r = self.session.get(self.baseUrl + '/fs/')
        self.files = r.json()
        self.result('Okay')
        
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
    else:
        with open(configFile) as f:
            print(configFile)
            print(f)
            config = json.load(f)
    
def loadArgs() -> Namespace:
    parser = argparse.ArgumentParser(description='CircuitPython HTTP API Loader')
    parser.add_argument('operation', help='operation to perform', choices=['upload', 'list', 'download', 'delete'])
    parser.add_argument('filename', help='filename to upload, download, or delete')
    parser.add_argument('-u', '--url', help='URL of the board', default='http://circuitpython.local')
    parser.add_argument('-d', '--device', help='ID of the device to use')
    return parser.parse_args()

def upload(args: Namespace):
    with open(args.filename, 'rb') as f:
        r = requests.put(args.url + '/fs/' + str(Path(args.filename).parent), headers={'Content-Type': 'application/octet-stream'}, data=f)

def commandWait(dev: Device) -> None:
    index = 0
    if not dev.connected:
        time.sleep(0.2)
        return
    print(' ', end='')
    while dev.outputQueue.empty() and dev.connected:
        print('\b' + loadingCursor[index], end='')
        index = (index + 1) % len(loadingCursor)
        time.sleep(0.2)
    print('\b', end='')



def showOutput(dev: Device):
    while True:
        while not dev.outputQueue.empty():
            output = dev.outputQueue.get()
            if 'task' in output:
                print(output['task'], end='')
            elif 'log' in output:
                print(output['log'])
            elif 'result' in output:
                print(output['result'])
            else:
                print(output)
            dev.outputQueue.task_done()
        if dev.running:
            commandWait(dev)
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
    
if __name__ == '__main__':
    main()
    


