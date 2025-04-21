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

import paho.mqtt.client as paho

import lvgl as lv


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
        result = shell(command)
        if callback:
            callback(result)
    t = threading.Thread(target=thread)
    t.start()
def run_async(callback):
    t = threading.Thread(target=callback)
    t.start()


DEBUG = os.getenv('DEBUG')
DEBUG = not not DEBUG
#DEBUG = True

SIMULATED_PRINTER = 'K3'


# Setup logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG if DEBUG else logging.INFO)

# Detect environment and tools
SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
USING_SIMULATOR = lv.helpers.is_windows()

if USING_SIMULATOR:
    KOBRA_MODEL = 'Anycubic Kobra'
    KOBRA_MODEL_CODE = SIMULATED_PRINTER
    KOBRA_VERSION = '1.2.3.4'

    if KOBRA_MODEL_CODE == 'KS1':
        QT_QPA_PLATFORM = 'linuxfb:fb=/dev/fb0:size=800x480:rotation=180:offset=0x0:nographicsmodeswitch'
    else:
        QT_QPA_PLATFORM = 'linuxfb:fb=/dev/fb0:size=480x272:rotation=90:offset=0x0:nographicsmodeswitch'
else:
    environment = shell(f'. /useremain/rinkhals/.current/tools.sh && python -c "import os, json; print(json.dumps(dict(os.environ)))"')
    environment = json.loads(environment)

    KOBRA_MODEL_ID = environment['KOBRA_MODEL_ID']
    KOBRA_MODEL = environment['KOBRA_MODEL']
    KOBRA_MODEL_CODE = environment['KOBRA_MODEL_CODE']
    KOBRA_VERSION = environment['KOBRA_VERSION']
    QT_QPA_PLATFORM = environment['QT_QPA_PLATFORM']
        
# Detect screen parameters
screen_options = QT_QPA_PLATFORM.split(':')
screen_options = [ o.split('=') for o in screen_options ]
screen_options = { o[0]: o[1] if len(o) > 1 else None for o in screen_options }

resolution_match = re.search('^([0-9]+)x([0-9]+)$', screen_options['size'])

SCREEN_WIDTH = int(resolution_match[1])
SCREEN_HEIGHT = int(resolution_match[2])
SCREEN_ROTATION = int(screen_options['rotation'])

if SCREEN_ROTATION % 180 == 90:
    (SCREEN_WIDTH, SCREEN_HEIGHT) = (SCREEN_HEIGHT, SCREEN_WIDTH)

if KOBRA_MODEL_CODE == 'KS1':
    TOUCH_CALIBRATION_MIN_X = 800
    TOUCH_CALIBRATION_MAX_X = 0
    TOUCH_CALIBRATION_MIN_Y = 480
    TOUCH_CALIBRATION_MAX_Y = 0
else:
    TOUCH_CALIBRATION_MIN_X = 25
    TOUCH_CALIBRATION_MAX_X = 460
    TOUCH_CALIBRATION_MIN_Y = 235
    TOUCH_CALIBRATION_MAX_Y = 25


class Program:
    display = None
    last_screen_check = 0

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

    def layout(self):
        colors = [
            lvr.COLOR_BACKGROUND,
            lv.color_mix(lvr.COLOR_BACKGROUND, lvr.COLOR_PRIMARY, 224)
        ]

        gradient = lv.grad_dsc()
        gradient.init_stops(colors, None, None, len(colors))
        gradient.linear_init(lv.pct(0), lv.pct(0), lv.pct(100), lv.pct(50), lv.GRAD_EXTEND.PAD)

        self.screen_welcome = lvr.screen()
        if self.screen_welcome:
            self.screen_welcome.set_style_bg_grad(gradient, lv.STATE_DEFAULT)
            self.screen_welcome.set_style_bg_opa(lv.OPA_COVER, lv.STATE_DEFAULT)

            self.screen_welcome.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            self.screen_welcome.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
            self.screen_welcome.set_style_pad_row(lv.dpx(25), lv.STATE_DEFAULT)

            image_rinkhals = lvr.image(self.screen_welcome)
            image_rinkhals.set_src(SCRIPT_PATH + '/icon.png')
            lvr.scale_image(image_rinkhals, lv.dpx(100))
            
            label_title = lvr.title(self.screen_welcome)
            label_title.set_text('Rinkhals Installer')

            button_start = lvr.button(self.screen_welcome)
            button_start.set_width(lv.dpx(200))
            button_start.set_style_margin_top(lv.dpx(20), lv.STATE_DEFAULT)
            button_start.add_event_cb(lambda e: self.show_screen(self.screen_main), lv.EVENT_CODE.CLICKED, None)
            button_start_label = lvr.label(button_start)
            button_start_label.set_text('Continue')
            button_start_label.center()

            def anim_1_cb(o, value, image_rinkhals=image_rinkhals, label_title=label_title):
                image_rinkhals.set_style_opa(value * 255 // 100, lv.STATE_DEFAULT)
                image_rinkhals.set_style_margin_top(-lv.dpx(int((100 - value) * 1.6)), lv.STATE_DEFAULT)
                label_title.set_style_opa(value * 255 // 100, lv.STATE_DEFAULT)

            def anim_2_cb(o, value, button_start=button_start):
                button_start.set_style_opa(value * 255 // 100, lv.STATE_DEFAULT)

            anim_1 = lv.anim()
            anim_1.set_exec_cb(anim_1_cb)
            anim_1.set_delay(500)
            anim_1.set_duration(750)
            anim_1.set_values(0, 100)
            anim_1.set_path_cb(lv.anim_path_ease_out)
            
            anim_2 = lv.anim()
            anim_2.set_exec_cb(anim_2_cb)
            anim_2.set_delay(500 + 750)
            anim_2.set_duration(750)
            anim_2.set_values(0, 100)
            anim_2.set_path_cb(lv.anim_path_ease_out)

        self.screen_main = lvr.screen()
        if self.screen_main:
            self.screen_main.set_style_bg_grad(gradient, lv.STATE_DEFAULT)
            self.screen_main.set_style_bg_opa(lv.OPA_COVER, lv.STATE_DEFAULT)
            self.screen_main.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            self.screen_main.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)

            image_rinkhals = lvr.image(self.screen_main)
            image_rinkhals.set_src(SCRIPT_PATH + '/icon.png')
            lvr.scale_image(image_rinkhals, lv.dpx(64))

            label_title = lvr.title(self.screen_main)
            label_title.set_text('Rinkhals Installer')
            label_title.align(lv.ALIGN.TOP_LEFT, lv.dpx(84), lv.dpx(0))

            label_version = lvr.subtitle(self.screen_main)
            label_version.set_text('dev')
            label_version.align(lv.ALIGN.TOP_LEFT, lv.dpx(84), lv.dpx(40))

            panel_tags = lvr.panel(self.screen_main)
            panel_tags.set_width(lv.pct(100))
            panel_tags.set_align(lv.ALIGN.BOTTOM_MID)
            panel_tags.set_style_bg_opa(lv.OPA_TRANSP, lv.STATE_DEFAULT)
            panel_tags.set_style_pad_all(0, lv.STATE_DEFAULT)
            panel_tags.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            panel_tags.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)

            tag_test_1 = lvr.tag(panel_tags)
            tag_test_1.set_icon('')
            tag_test_1.set_text('Configuration error')
            tag_test_1.set_color(lv.color_make(160, 0, 0))
            
            tag_test_2 = lvr.tag(panel_tags)
            tag_test_2.set_icon('')
            tag_test_2.set_text('Everything is awesome!')
            tag_test_2.set_color(lv.color_make(0, 160, 0))


            button_install = lvr.button(self.screen_main)
            button_install.set_width(lv.pct(100))
            button_install_label = lv.label(button_install)
            button_install_label.set_text('Install / Update')
            button_install_label.center()

            button_tools = lvr.button(self.screen_main)
            button_tools.set_width(lv.pct(100))
            button_tools_label = lv.label(button_tools)
            button_tools_label.set_text('Tools')
            button_tools_label.center()

            button_diagnostics = lvr.button(self.screen_main)
            button_diagnostics.set_width(lv.pct(100))
            button_diagnostics_label = lv.label(button_diagnostics)
            button_diagnostics_label.set_text('Diagnostics')
            button_diagnostics_label.center()

        lv.screen_load(self.screen_main)

        anim_1.start()
        anim_2.start()

    def show_screen(self, screen):
        parent = screen.get_parent()
        if parent:
            screen.move_foreground()
        else:
            lv.screen_load(screen)

        #if screen == self.screen_main: self.layout_main()

    def run(self):
        while True:
            lv.tick_inc(16)
            lv.timer_handler()
            time.sleep(0.016)


if __name__ == "__main__":
    if USING_SIMULATOR:
        program = Program()
        program.run()
    else:
        try:
            program = Program()
            program.run()
        except:
            frames = sys._current_frames()
            threads = {}
            for thread in threading.enumerate():
                threads[thread.ident] = thread
            for thread_id, stack in frames.items():
                if thread_id == threading.main_thread().ident:
                    print(traceback.format_exc())
                elif thread_id in threads:
                    print(f'-- Thread {thread_id}: {threads[thread_id]} --')
                    print(' '.join(traceback.format_list(traceback.extract_stack(stack))))
            
    print('', flush=True)
    os.kill(os.getpid(), 9)
