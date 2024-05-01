# Code which runs on host computer and implements the GUI plot panels.
# Copyright (c) Thomas Akam 2018-2023.  Licenced under the GNU General Public License v3.

import numpy as np
import pyqtgraph as pg
from datetime import datetime
from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
from pyqtgraph.Qt.QtWidgets import QFrame

from config.GUI_config import history_dur, triggered_dur, max_plot_pulses

# Signals_plot ------------------------------------------------------


class Signals_plot(QtWidgets.QWidget):

    """Class for plotting data from one setup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        # Create axis
        self.axis = pg.PlotWidget(title="Analog signal", labels={"left": "Volts"})
        self.axis.setMouseEnabled(x=False, y=False)
        self.axis.getPlotItem().setMenuEnabled(False)
        self.axis.disableAutoRange()
        self.legend = self.axis.addLegend(offset=(10, 10))
        self.axis.setYRange(-0.1, 3.3, padding=0)
        self.axis.setXRange(-history_dur, 0.2, padding=0)
        self.axis.setLimits(xMin=-history_dur, xMax=0.2)

        # Plotting classes
        self.plots = [
            self.axis.plot(pen=pg.mkPen("g"), name="analog 1"),
            self.axis.plot(pen=pg.mkPen("r"), name="analog 2"),
        ]
        self.DI_shaders = [
            Pulse_shader(self.axis, brush=(0, 0, 225, 80)),
            Pulse_shader(self.axis, brush=(225, 225, 0, 80)),
        ]
        self.event_triggered_plot = Event_triggered_plot(self)
        self.event_triggered_plot.axis.setVisible(False)
        self.record_clock = Record_clock(self.axis)

        # Create controls
        self.yrange_label = QtWidgets.QLabel("Y range:")
        self.fullrange_button = QtWidgets.QPushButton("Full")
        self.fullrange_button.setFixedWidth(50)
        self.fullrange_button.clicked.connect(self.fullscale)
        self.autoscale_button = QtWidgets.QPushButton("Auto")
        self.autoscale_button.setFixedWidth(50)
        self.autoscale_button.clicked.connect(self.autoscale)
        self.zoom_out_button = QtWidgets.QPushButton("-")
        self.zoom_out_button.setFixedWidth(30)
        self.zoom_out_button.clicked.connect(lambda x: self.scale_y(1.25))
        self.zoom_in_button = QtWidgets.QPushButton("+")
        self.zoom_in_button.setFixedWidth(30)
        self.zoom_in_button.clicked.connect(lambda x: self.scale_y(0.75))
        self.demean_checkbox = QtWidgets.QCheckBox("De-mean plotted signals")
        self.demean_checkbox.stateChanged.connect(self.enable_disable_demean_mode)
        self.offset_label = QtWidgets.QLabel("Offset channels (mV):")
        self.offset_spinbox = QtWidgets.QSpinBox()
        self.offset_spinbox.valueChanged.connect(lambda x: setattr(self, "autoscale_next_update", True))
        self.offset_spinbox.setSingleStep(10)
        self.offset_spinbox.setMaximum(500)
        self.offset_spinbox.setValue(100)
        self.offset_spinbox.setFixedWidth(50)
        self.etp_checkbox = QtWidgets.QCheckBox("Show event triggered plot")
        self.etp_checkbox.stateChanged.connect(self.show_hide_event_triggered_plot)
        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.addWidget(self.yrange_label)
        self.controls_layout.addWidget(self.fullrange_button)
        self.controls_layout.addWidget(self.autoscale_button)
        self.controls_layout.addWidget(self.zoom_out_button)
        self.controls_layout.addWidget(self.zoom_in_button)
        self.controls_layout.addWidget(QFrame(frameShape=QFrame.Shape.VLine, frameShadow=QFrame.Shadow.Sunken))
        self.controls_layout.addWidget(self.demean_checkbox)
        self.controls_layout.addWidget(self.offset_label)
        self.controls_layout.addWidget(self.offset_spinbox)
        self.controls_layout.addWidget(QFrame(frameShape=QFrame.Shape.VLine, frameShadow=QFrame.Shadow.Sunken))
        self.controls_layout.addWidget(self.etp_checkbox)
        self.controls_layout.addStretch()

        self.enable_disable_demean_mode()

        # Main layout
        self.vertical_layout = QtWidgets.QVBoxLayout()
        self.vertical_layout.setContentsMargins(0, 0, 0, 0)
        self.vertical_layout.addLayout(self.controls_layout)
        self.vertical_layout.addWidget(self.axis)
        self.vertical_layout.addWidget(self.event_triggered_plot.axis)
        self.setLayout(self.vertical_layout)

    def set_n_signals(self, n_analog_signals):
        if len(self.plots) == 2 and n_analog_signals == 3:
            self.plots.append(self.axis.plot(pen=pg.mkPen("m"), name="analog 3"))
        elif len(self.plots) == 3 and n_analog_signals == 2:
            self.axis.removeItem(self.plots.pop(-1))

    def reset(self, sampling_rate):
        history_length = int(sampling_rate * history_dur)
        self.autoscale_next_update = False
        self.ADCs = [
            Signal_history(history_length),
            Signal_history(history_length),
            Signal_history(history_length),
        ]
        self.DIs = [
            Signal_history(history_length, int),
            Signal_history(history_length, int),
        ]
        self.x = np.linspace(-history_dur, 0, history_length)  # X axis for timeseries plots.

        self.DI_shaders[0].reset(self.DIs[0], self.x)
        self.DI_shaders[1].reset(self.DIs[1], self.x)
        self.event_triggered_plot.reset(sampling_rate)

    def update(self, new_ADCs, new_DIs):
        new_ADCs = [3.3 * new_ADC / (1 << 15) for new_ADC in new_ADCs]  # Convert to Volts.
        for i, new_ADC in enumerate(new_ADCs):
            self.ADCs[i].update(new_ADC)
            if self.AC_mode:  # Plot signals with mean removed.
                y = self.ADCs[i].history - np.nanmean(self.ADCs[i].history) - i * self.offset_spinbox.value() / 1000
            else:
                y = self.ADCs[i].history
            self.plots[i].setData(self.x, y)
        for i, new_DI in enumerate(new_DIs):
            self.DIs[i].update(new_DI)
            self.DI_shaders[i].update()
        self.event_triggered_plot.update(len(new_ADCs[0]))
        if self.autoscale_next_update:
            self.autoscale()
            self.autoscale_next_update = False
        self.record_clock.update()

    def enable_disable_demean_mode(self):
        if self.demean_checkbox.isChecked():
            self.AC_mode = True
            self.offset_spinbox.setEnabled(True)
            self.offset_label.setStyleSheet("color : black")
        else:
            self.AC_mode = False
            self.offset_spinbox.setEnabled(False)
            self.offset_label.setStyleSheet("color : gray")
        if self.parent.is_running():
            self.autoscale_next_update = True

    def show_hide_event_triggered_plot(self):
        if self.etp_checkbox.isChecked():
            self.event_triggered_plot.axis.setVisible(True)
        else:
            self.event_triggered_plot.axis.setVisible(False)

    def autoscale(self):
        """Set the Y axis ranges to show all the data"""
        self.axis.autoRange(padding=0.1)

    def fullscale(self):
        """Set the Y axis ranges to show the full signal range, turn of Demean mode if on."""
        if self.AC_mode:
            self.demean_checkbox.setChecked(False)
            self.autoscale_next_update = False
        self.axis.setYRange(-0.1, 3.3, padding=0)

    def scale_y(self, s):
        """Zoom in or out the Y scale by specified factor."""
        self.axis.getPlotItem().getViewBox().scaleBy(y=s)


class Pulse_shader:
    """Class for plotting pulses as shaded regions on Signals_plot."""

    def __init__(self, axis, brush):
        self.axis = axis
        self.pulses = []
        self.brush = brush

    def reset(self, DI, x):
        self.DI = DI
        self.x = x
        for pulse in self.pulses:
            self.axis.removeItem(pulse)
        self.pulses = []

    def update(self):
        pulse_starts = self.x[np.where(np.diff(self.DI.history) == 1)[0] + 1]
        pulse_ends = self.x[np.where(np.diff(self.DI.history) == -1)[0] + 1]
        if self.DI.history[0] == 1:
            pulse_starts = np.hstack([self.x[0], pulse_starts])
        if self.DI.history[-1] == 1:
            pulse_ends = np.hstack([pulse_ends, self.x[-1]])
        pulse_times = list(zip(pulse_starts, pulse_ends))[-max_plot_pulses:]  # Limit number of pulses to show.
        for i, (pulse_start, pulse_end) in enumerate(pulse_times):
            try:  # Update location of existing pulses.
                self.pulses[i].setRegion([pulse_start, pulse_end])
            except IndexError:  # Create new pulses.
                pulse = pg.LinearRegionItem([pulse_start, pulse_end], brush=self.brush, pen=(0, 0, 0, 0), movable=False)
                self.pulses.append(pulse)
                self.axis.addItem(pulse)
        if len(self.pulses) > len(pulse_starts):  # Hide unused pulses.
            for pulse in self.pulses[len(pulse_starts) :]:
                pulse.setRegion([0, 0])


# Event triggered plot -------------------------------------------------


class Event_triggered_plot:
    def __init__(self, signals_plot, tau=5):
        self.signals_plot = signals_plot
        self.axis = pg.PlotWidget(title="Event triggered", labels={"left": "Volts", "bottom": "Time (seconds)"})
        self.axis.setMouseEnabled(x=False, y=False)
        self.axis.addLegend(offset=(-10, 10))
        self.prev_plot = self.axis.plot(pen=pg.mkPen(pg.hsvColor(0.6, sat=0, alpha=0.3)), name="latest")
        self.ave_plot = self.axis.plot(pen=pg.mkPen(pg.hsvColor(0.6)), name="average")
        self.axis.addItem(pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(style=QtCore.Qt.PenStyle.DotLine)))
        self.axis.setXRange(triggered_dur[0], triggered_dur[1], padding=0)
        self.alpha = 1 - np.exp(-1.0 / tau)  # Learning rate for update of average trace, tau is time constant.

    def reset(self, sampling_rate):
        self.window = (np.array(triggered_dur) * sampling_rate).astype(
            int
        )  # Window for event triggered signals (samples [pre, post])
        self.x = np.linspace(*triggered_dur, self.window[1] - self.window[0])  # X axis for event triggered plots.
        self.average = None
        self.prev_plot.clear()
        self.ave_plot.clear()

    def update(self, new_data_len):
        # Update event triggered average plot.
        trig_section = self.signals_plot.DIs[0].history[-self.window[1] - new_data_len - 1 : -self.window[1]]
        rising_edges = np.where(np.diff(trig_section) == 1)[0]
        for i, edge in enumerate(rising_edges):
            edge_ind = -self.window[1] - new_data_len - 1 + edge  # Position of edge in signal history.
            ev_trig_sig = self.signals_plot.ADCs[0].history[edge_ind + self.window[0] : edge_ind + self.window[1]]
            if self.average is None:  # First acquisition
                self.average = ev_trig_sig
            else:  # Update averaged trace.
                self.average = (1 - self.alpha) * self.average + self.alpha * ev_trig_sig
            if i + 1 == len(rising_edges):
                self.prev_plot.setData(self.x, ev_trig_sig)
                self.ave_plot.setData(self.x, self.average)


# Signal_history ------------------------------------------------------------


class Signal_history:
    # Buffer to store the recent history of a signal.

    def __init__(self, history_length, dtype=float):
        self.history = np.full(history_length, np.nan if dtype == float else 0, dtype)

    def update(self, new_data):
        # Move old data along buffer, store new data samples.
        data_len = len(new_data)
        self.history = np.roll(self.history, -data_len)
        self.history[-data_len:] = new_data


# Record_clock ----------------------------------------------------


class Record_clock:
    # Class for displaying the run time.

    def __init__(self, axis):
        self.clock_text = pg.TextItem(text="")
        self.clock_text.setFont(QtGui.QFont("arial", 12, QtGui.QFont.Weight.Bold))
        axis.getViewBox().addItem(self.clock_text, ignoreBounds=True)
        self.clock_text.setParentItem(axis.getViewBox())
        self.clock_text.setPos(240, 10)
        self.recording_text = pg.TextItem(text="", color=(255, 0, 0))
        self.recording_text.setFont(QtGui.QFont("arial", 12, QtGui.QFont.Weight.Bold))
        axis.getViewBox().addItem(self.recording_text, ignoreBounds=True)
        self.recording_text.setParentItem(axis.getViewBox())
        self.recording_text.setPos(110, 10)
        self.start_time = None

    def start(self):
        self.start_time = datetime.now()
        self.recording_text.setText("Recording")

    def update(self):
        if self.start_time:
            self.clock_text.setText(str(datetime.now() - self.start_time)[:7])

    def stop(self):
        self.clock_text.setText("")
        self.recording_text.setText("")
        self.start_time = None
