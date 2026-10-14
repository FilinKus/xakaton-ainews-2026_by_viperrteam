from logger import *
import news_collector_ai
from PySide6.QtWidgets import *
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import Qt#, QFont, QIcon,
from sys import argv
import os
import threading
from datetime import datetime
from pathlib import Path

def check_for_output_folder():
    pass

default_links = [
    'https://www.securitylab.ru', 
    'https://xakep.ru',
    'https://www.comnews.ru/information_security',
    'https://www.kommersant.ru/theme/1267',
    'https://tass.ru/',
    'https://ria.ru/kiberbezopasnost',
    'https://www.it-world.ru/security/',
    'https://securitymedia.org',
    'https://www.infowatch.ru/analytics/novosti-ib',
    'https://infobezopasnost.ru/blog/news/',
    'https://ict.moscow/projects/cybersecurity/',
    'https://www.gazeta.ru/tech',
    'https://aif.ru/techno/web',
    'https://safe.cnews.ru',
    'https://habr.com/ru/hubs/infosecurity/',
    'https://rb.ru/tag/cybersecurity/',
    'https://3dnews.ru/security',
    'https://www.computerra.ru/tag/security/',
    'https://www.itweek.ru/security/',
    'https://www.ixbt.com/live/security/',
    'https://overclockers.ru/tag/security',
    'https://rg.ru/theme/technologies/internet/kiberbezopasnost/',
    'https://iz.ru/tag/kiberbezopasnost',
    'https://ptsecurity.com/research/analytics/',
    'https://rt-solar.ru/events/news/',
    'https://www.kaspersky.ru/about/press-releases',
    'https://www.usergate.com/ru',
    'https://infotecs.ru'
]

selected_links = default_links

def log(text):
    print_log(log_text, text)

def log_to_json():
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / ('log-' + '{date:%Y-%m-%d-%H-%M-%S}'.format(date=datetime.now()) + '.json')
    file_path.write_text(log_text.toPlainText(), encoding="utf-8")
    os.startfile(file_path)

def modify_link(enable=True, link=None):
    if link is not None:
        if enable and link not in selected_links:
            log(f"'{link}' будет проверена")
            selected_links.append(link)
        elif not enable and link in selected_links:
            log(f"'{link}' не будет проверена")
            selected_links.remove(link)

def add_checkbox(text=None, checked=False):
    if text is None:
        text = f'unnamed #{checkbox_layout.count() + 1}'

    checkbox = QCheckBox(text)
    checkbox.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    checkbox.setFixedHeight(32)
    # checkbox.setFont(QFont('Palatino Linotype', 8))

    checkbox.setSizePolicy(
        checkbox.sizePolicy().Policy.Expanding,
        checkbox.sizePolicy().Policy.Fixed,
    )

    log(f'Добавлена ссылка f{text}')

    checkbox.toggled.connect(lambda checked, link=text: modify_link(checked, link))

    checkbox_layout.addWidget(checkbox)

def auto_scroll(min_val, max_val):
    scrollbar = log_text.verticalScrollBar()
    
    if max_val - scrollbar.value() <= 10: 
        scrollbar.setValue(max_val)

loader = QUiLoader()

app = QApplication(argv)

app.aboutToQuit.connect(news_collector_ai.stop_local_ollama)
window = loader.load('main.ui', None)

window.setWindowTitle('News AI')
window.show()


checkbox_layout = window.findChild(QVBoxLayout, 'checkbox_layout')
log_text = window.findChild(QPlainTextEdit, 'log_text')
log_text.verticalScrollBar().rangeChanged.connect(auto_scroll)
start_button = window.findChild(QPushButton, 'start')
save_log = window.findChild(QPushButton, 'save_log')
save_log.pressed.connect(log_to_json)


def aistart():
    background_thread = threading.Thread(
        target=news_collector_ai.start, 
        args=(selected_links, log_text),
        daemon=True
    )
    background_thread.start()
    # news_collector_ai.start(selected_links, log_text)

start_button.pressed.connect(aistart)

for i in default_links:
    add_checkbox(str(i), True)

app.exec()

news_collector_ai.stop_local_ollama()