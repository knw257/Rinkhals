from enum import Enum
import os
import time
import sys
import json
import re
import random
import threading
import traceback
import logging
import psutil
import requests
import subprocess
import hashlib

import lvgl as lv


class JSONWithCommentsDecoder(json.JSONDecoder):
    def __init__(self, **kwgs):
        super().__init__(**kwgs)
    def decode(self, s: str):
        regex = r"""("(?:\\"|[^"])*?")|(\/\*(?:.|\s)*?\*\/|\/\/.*)"""
        s = re.sub(regex, r"\1", s)  # , flags = re.X | re.M)
        return super().decode(s)



RINKHALS_BASE = '/useremain/rinkhals'


SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
USING_SIMULATOR = lv.helpers.is_windows()




KOBRA_MODEL_ID = None
KOBRA_MODEL = None
KOBRA_MODEL_CODE = None
KOBRA_VERSION = None

# Try to detect printer model
try:
    with open('/userdata/app/gk/config/api.cfg', 'r') as f:
        api_config = json.loads(f.read())

    KOBRA_MODEL_ID = api_config['cloud']['modelId']

    if KOBRA_MODEL_ID == '20021':
        KOBRA_MODEL = 'Anycubic Kobra 2 Pro'
        KOBRA_MODEL_CODE = 'K2P'
    elif KOBRA_MODEL_ID == '20024':
        KOBRA_MODEL = 'Anycubic Kobra 3'
        KOBRA_MODEL_CODE = 'K3'
    elif KOBRA_MODEL_ID == '20025':
        KOBRA_MODEL = 'Anycubic Kobra S1'
        KOBRA_MODEL_CODE = 'KS1'
    elif KOBRA_MODEL_ID == '20026':
        KOBRA_MODEL = 'Anycubic Kobra 3 Max'
        KOBRA_MODEL_CODE = 'K3M'
except:
    pass

# Try to detect firmware version
try:
    with open('/useremain/dev/version', 'r') as f:
        KOBRA_VERSION = f.read().strip()
except:
    pass



# Try to detect screen parameters



# screen_options = QT_QPA_PLATFORM.split(':')
# screen_options = [ o.split('=') for o in screen_options ]
# screen_options = { o[0]: o[1] if len(o) > 1 else None for o in screen_options }

# resolution_match = re.search('^([0-9]+)x([0-9]+)$', screen_options['size'])

# SCREEN_WIDTH = int(resolution_match[1])
# SCREEN_HEIGHT = int(resolution_match[2])
# SCREEN_ROTATION = int(screen_options['rotation'])

# if SCREEN_ROTATION % 180 == 90:
#     (SCREEN_WIDTH, SCREEN_HEIGHT) = (SCREEN_HEIGHT, SCREEN_WIDTH)



class DiagnosticType(Enum):
    OK = 1
    WARNING = 2
    ERROR = 3
    
class DiagnosticFixes(Enum):
    REINSTALL_FIRMWARE = 1
    REINSTALL_RINKHALS = 2
    RESET_CONFIGURATION = 3

class Diagnostic:
    type = 0
    short_text = ''
    long_text = ''
    fix = None

    def __init__(self, type, short_text, long_text, fix=None):
        self.type = type
        self.short_text = short_text
        self.long_text = long_text
        self.fix = fix


class Helpers:
    def shell(command):
        if USING_SIMULATOR:
            result = subprocess.check_output(['sh', '-c', command])
            result = result.decode('utf-8').strip()
        else:
            temp_output = f'/tmp/rinkhals/output-{random.randint(1000, 9999)}'

            os.system(f'{command} > {temp_output}')
            if os.path.exists(temp_output):
                with open(temp_output) as f:
                    result = f.read().strip()
                os.remove(temp_output)
            else:
                result = ''

        logging.info(f'Shell "{command}" => "{result}"')
        return result
    def shell_async(command, callback):
        def thread():
            result = Helpers.shell(command)
            if callback:
                callback(result)
        t = threading.Thread(target=thread)
        t.start()
    def run_async(callback):
        t = threading.Thread(target=callback)
        t.start()

    def hash(path):
        if not os.path.exists(path):
            return None
        
        md5 = hashlib.md5()

        with open(path, 'rb') as f:
            while True:
                data = f.read(8192)
                if not data:
                    break
                md5.update(data)

        return md5.hexdigest()


    def get_installed_rinkhals():
        if os.path.exists(RINKHALS_BASE):
            return [ f.path for f in os.scandir(RINKHALS_BASE) if f.is_dir() ]



    def run_diagnostics():
        # Detect if environment cannot be identified
        if KOBRA_MODEL_ID is None or KOBRA_VERSION is None:
            yield Diagnostic(DiagnosticType.ERROR, 'Unknown environment', 'Unable to detect environment, your printer might be corrupted', DiagnosticFixes.REINSTALL_FIRMWARE)

        # Detect if printer.cfg has been modified
        printer_cfg_path = '/userdata/app/gk/printer.cfg'

        if not os.path.exists(printer_cfg_path):
            yield Diagnostic(DiagnosticType.ERROR, 'Missing configuration', 'Unable to find default printer.cfg', DiagnosticFixes.REINSTALL_FIRMWARE)
        else:
            printer_cfg_hash = Helpers.hash(printer_cfg_path)
            supposed_hash = None

            if KOBRA_MODEL_CODE == 'K3':
                if KOBRA_VERSION == '2.2.9.6': supposed_hash = None
                if KOBRA_VERSION == '2.3.3.2': supposed_hash = None
                if KOBRA_VERSION == '2.3.3.9': supposed_hash = None
                if KOBRA_VERSION == '2.3.5.3': supposed_hash = 'ed893ad8de97e52945c0f036acb1317e'
                if KOBRA_VERSION == '2.3.7':   supposed_hash = '6ae0f83abbd517232e03e9183984b5c8'
                if KOBRA_VERSION == '2.3.7.1': supposed_hash = '6ae0f83abbd517232e03e9183984b5c8'
                if KOBRA_VERSION == '2.3.8':   supposed_hash = 'addcb2cc9e34a867f49a7396bfdf276c'
                if KOBRA_VERSION == '2.3.8.9': supposed_hash = '0e6c2c875b997d861afa83c7453f5b6a'
            elif KOBRA_MODEL_CODE == 'KS1':
                if KOBRA_VERSION == '2.4.8.3': supposed_hash = '6ca031c6b72b86bb6a78311b308b2163'
                if KOBRA_VERSION == '2.5.0.2': supposed_hash = 'e142ceaba7a7fe56c1f5d51d15be2b96'
                if KOBRA_VERSION == '2.5.0.6': supposed_hash = 'c2d6967dce8803a20c3087b4e2764633'
                if KOBRA_VERSION == '2.5.1.6': supposed_hash = 'f41fdca985d7fdb02d561f5d271eb526'
            elif KOBRA_MODEL_CODE == 'K2P':
                if KOBRA_VERSION == '3.1.2.3': supposed_hash = 'fb945efa204eec777a139adafc6a40aa'
                if KOBRA_VERSION == '3.1.4':   supposed_hash = None
            elif KOBRA_MODEL_CODE == 'K3M':
                if KOBRA_VERSION == '2.4.4':   supposed_hash = None
                if KOBRA_VERSION == '2.4.4.9': supposed_hash = None

            if supposed_hash is None:
                printer_cfg_mtime = os.path.getmtime(printer_cfg_path)
                api_cfg_mtime = os.path.getmtime('/userdata/app/gk/config/api.cfg')

                if abs(printer_cfg_mtime - api_cfg_mtime) > 5:
                    yield Diagnostic(DiagnosticType.WARNING, 'Modified configuration', 'Your printer.cfg has likely been modified', DiagnosticFixes.REINSTALL_FIRMWARE)

            elif printer_cfg_hash != supposed_hash:
                yield Diagnostic(DiagnosticType.WARNING, 'Modified configuration', 'Your printer.cfg has been modified', DiagnosticFixes.REINSTALL_FIRMWARE)

        # Detect if some configuration customizations are present
        custom_cfg_path = '/useremain/home/rinkhals/printer_data/config/printer.custom.cfg'
        if os.path.exists(custom_cfg_path):
            try:
                with open(custom_cfg_path, 'r') as f:
                    custom_lines = f.readlines()
            
                custom_lines = [ l for l in custom_lines if custom_lines.strip() and not custom_lines.strip().startswith('#') ]
                if len(custom_lines) > 0:
                    yield Diagnostic(DiagnosticType.WARNING, 'Customized configuration', 'You have printer configuration customizations', DiagnosticFixes.RESET_CONFIGURATION)
            except:
                pass

        # TODO: Detect if there are more than one bed meshes
        # TODO: Detect if LAN mode is enabled




class BaseProgram:


    def __init__(self):
        lv.init()

        if lv.helpers.is_windows():
            self.display = lv.windows_create_display('Rinkhals', SCREEN_WIDTH, SCREEN_HEIGHT, 100, False, True)
            touch = lv.windows_acquire_pointer_indev(self.display)
            touch.set_display(self.display)

        elif lv.helpers.is_linux():
            self.display = lv.linux_fbdev_create()
            lv.linux_fbdev_set_file(self.display, '/dev/fb0')

            if SCREEN_ROTATION == 0: self.display.set_rotation(lv.DISPLAY_ROTATION._0)
            elif SCREEN_ROTATION == 90: self.display.set_rotation(lv.DISPLAY_ROTATION._270)
            elif SCREEN_ROTATION == 180: self.display.set_rotation(lv.DISPLAY_ROTATION._180)
            elif SCREEN_ROTATION == 270 or SCREEN_ROTATION == -90: self.display.set_rotation(lv.DISPLAY_ROTATION._90)

            touch = lv.evdev_create(lv.INDEV_TYPE.POINTER, '/dev/input/event0')
            touch.set_display(self.display)
            
            lv.evdev_grab_device(touch)
            lv.evdev_set_calibration(touch, TOUCH_CALIBRATION_MIN_X, TOUCH_CALIBRATION_MIN_Y, TOUCH_CALIBRATION_MAX_X, TOUCH_CALIBRATION_MAX_Y)

            def screen_sleep_cb(e):
                if time.time() - self.last_screen_check > 5:
                    self.last_screen_check = time.time()
                    brightness = shell('cat /sys/class/backlight/backlight/brightness')
                    if brightness == '0':
                        os.system('echo 255 > /sys/class/backlight/backlight/brightness')

            touch.add_event_cb(screen_sleep_cb, lv.EVENT_CODE.CLICKED, None)

        if KOBRA_MODEL_CODE == 'KS1':
            self.display.set_dpi(180)
        else:
            self.display.set_dpi(130)

        # Layout and draw
        global lvr
        import lvgl_rinkhals as lvr

        self.layout()



    def quit(self):
        logging.info('Exiting Rinkhals UI...')
        time.sleep(0.25)
        os.kill(os.getpid(), 9)


    def run(self):
        while True:
            lv.tick_inc(16)
            lv.timer_handler()
            time.sleep(0.016)

