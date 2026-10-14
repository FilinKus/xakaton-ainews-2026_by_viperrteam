from PySide6.QtWidgets import QPlainTextEdit
# from PySide6.QtUiTools import QUiLoader
# from PySide6.QtGui import QFont, QIcon, Qt
from PySide6.QtCore import QObject, Signal
# from PySide6.QtGui import QPalette, QColor
import datetime

class LogSignaler(QObject):
    text_ready = Signal(QPlainTextEdit, str)

def print_log(textedit, text):
    signal_logger.text_ready.emit(textedit, text)

def teappend(textedit, text):
    textedit.appendPlainText('{date:%Y-%m-%d %H:%M:%S}'.format(date=datetime.datetime.now()) + '  ||  ' + text)

signal_logger = LogSignaler()
signal_logger.text_ready.connect(teappend)