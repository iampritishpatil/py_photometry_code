# Code which runs on host computer and implements the graphical user interface.
# Copyright (c) Thomas Akam 2018-2023.  Licenced under the GNU General Public License v3.

import os
import sys
import ctypes
import traceback
import logging
#from pyqtgraph.Qt import QtGui, QtWidgets, QtCore
from PySide6 import QtCore, QtWidgets, QtGui

import config.GUI_config as GUI_config
from GUI.acquisition_tab import Acquisition_tab
from GUI.setups_tab import Setups_tab
from threading import Thread
from threading import Event
import zmq # added by LIOR SEGEV for communicaitn with EPA qt application
from time import sleep # added by LIOR SEGEV for communicaitn with EPA qt application

if os.name == "nt":  # Needed on windows to get taskbar icon to display correctly.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("pyPhotometry")

# added by LIOR SEGEV for communicaitn with EPA qt application
# zeromq server for communication with EPA application
import zmq

class ZMQ_server:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind("tcp://127.0.0.1:5557")
        self.terminate_thread_event = Event()
        self.server_thread = Thread(target=self.run_server)
        self.server_thread.start()

    def run_server(self):
        while not self.terminate_thread_event.is_set():

            message = self.socket.recv()
            print("Received request: %s" % message)
            self.parent_window.handle_message(message)
            self.socket.send_string("Message_recieved")

            sleep(0.1)

# ------------------------------------------------------------------ END addition by LIOR SEGEV

# Photometry_GUI ------------------------------------------------------------------


class GUI_main(QtWidgets.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("pyPhotometry GUI v{}".format(GUI_config.VERSION))
        self.setGeometry(100, 100, 1000, 1080)  # Left, top, width, height.

        # Variables
        self.refresh_interval = 1000  # Interval to refresh tasks and ports when not running (ms).
        self.current_tab_ind = 0  # Which tab is currently selected.

        # Widgets.
        self.tab_widget = QtWidgets.QTabWidget(self)
        self.setCentralWidget(self.tab_widget)

        self.setups_tab = Setups_tab(self)
        self.acquisition_tab = Acquisition_tab(self)

        self.tab_widget.addTab(self.acquisition_tab, "Acquisition")
        self.tab_widget.addTab(self.setups_tab, "Setups")
        self.tab_widget.currentChanged.connect(self.tab_changed)

        # Keyboard Shortcuts

        fullscale_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self)
        fullscale_shortcut.activated.connect(self.acquisition_tab.set_full_Yscale)

        autoscale_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+A"), self)
        autoscale_shortcut.activated.connect(self.acquisition_tab.set_auto_Yscale)

        demean_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+D"), self)
        demean_shortcut.activated.connect(self.acquisition_tab.toggle_demean_mode)

        # Timers

        self.refresh_timer = QtCore.QTimer()  # Timer to regularly call refresh() when not running.
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh()  # Refresh ports list.
        self.refresh_timer.start(self.refresh_interval)

        # run zeromq server for communication with EPA application
        self.zmq_server = ZMQ_server(self)
    
    def handle_message(self, message):
        print(
            "Message recieved: {}".format(message)
        )
        if message == b"start":
            self.acquisition_tab.setupboxes[0].start_button.clicked.emit()
            self.acquisition_tab.setupboxes[0].record_button.clicked.emit()
        elif message == b'stop':
            self.acquisition_tab.setupboxes[0].stop_button.clicked.emit()


        # emit the correct order of signals to the acquisition tab to be done!


    def refresh(self):
        # Called regularly while not running to update tabs.
        self.acquisition_tab.refresh()
        self.setups_tab.refresh()

    def tab_changed(self, new_tab_ind):
        """Called whenever the active tab is changed."""
        if self.current_tab_ind == 0:
            self.acquisition_tab.disconnect()
        self.current_tab_ind = new_tab_ind

    def closeEvent(self, event):
        """Called when GUI window is closed."""
        # LIOR SEGEV
        self.zmq_server.socket.close()
        self.zmq_server.terminate_thread_event.set()
        self.zmq_server.server_thread.join()
        #-- LIOR SEGEV
        if self.current_tab_ind == 0:
            self.acquisition_tab.disconnect()
        event.accept()

    # Exception handling.

    def excepthook(self, ex_type, ex_value, ex_traceback):
        """Called when an uncaught exception occurs, shows error message and traceback in dialog."""
        logging.error("".join(traceback.format_exception(ex_type, ex_value, ex_traceback)))


# --------------------------------------------------------------------------------
# Launch GUI.
# --------------------------------------------------------------------------------


def launch_GUI():
    """Launch the pyPhotometry GUI."""
    app = QtWidgets.QApplication([])  # Start QT
    app.setStyle("Fusion")
    app.setWindowIcon(QtGui.QIcon("gui/icons/logo.svg"))
    photometry_GUI = GUI_main(app)
    photometry_GUI.show()
    sys.excepthook = photometry_GUI.excepthook
    app.exec()
