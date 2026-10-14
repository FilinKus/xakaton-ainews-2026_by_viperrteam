from logger import *
import os
import sys
import time
import subprocess
import shutil
import atexit
import threading
import requests
from openai import OpenAI
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from openai import OpenAI
# import html2text
# from urllib.parse import urljoin
import httpx
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

is_running = False
log_text = 1

def log(text):
    print_log(log_text, text)

client = OpenAI(
    base_url='http://localhost:11434/v1', 
    api_key='ollama',
    timeout=httpx.Timeout(120.0, connect=60.0, read=None, write=20.0) 
)
MODEL_NAME = 'gemma2:9b' 
MY_TOPICS = [ 'кибербезопасность', 'мошенничество', 'защита личных данных', 'кибератаки' ]
MAX_NEWS_AGE_DAYS = 5  

ollama_process = None
_ollama_stop_lock = threading.Lock()

def find_ollama_exe(base_dir):
    """Ищет Ollama в PATH, стандартных каталогах Windows и папке проекта."""
    candidates = []
    ollama_in_path = shutil.which("ollama.exe") or shutil.which("ollama")
    if ollama_in_path:
        candidates.append(Path(ollama_in_path))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
    candidates.extend([
        Path(base_dir) / "Ollama" / "ollama.exe",
        Path(base_dir) / "ollama" / "ollama.exe",
        Path(base_dir) / "ollama.exe",
    ])

    checked = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
            if candidate not in checked and candidate.is_file():
                return str(candidate)
            checked.add(candidate)
        except (OSError, RuntimeError):
            continue
    return None


def start_local_ollama():
    global ollama_process

    if ollama_process is not None and ollama_process.poll() is None:
        log('Ollama уже запущена этим приложением.')
        return True

    log('Поиск Ollama на компьютере...')
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    ollama_path = find_ollama_exe(base_dir)
    if not ollama_path:
        log(
            'Критическая ошибка: Ollama не найдена. '
            'Установите её с https://ollama.com/download/windows '
            'или добавьте ollama.exe в PATH.'
        )
        return False

    log(f'Найдена Ollama: {ollama_path}')

    local_models_dir = os.path.join(base_dir, 'models')
    env = os.environ.copy()
    if os.path.isdir(local_models_dir):
        env['OLLAMA_MODELS'] = local_models_dir

    startupinfo = None
    creationflags = 0
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    try:
        try:
            response = requests.get('http://127.0.0.1:11434/', timeout=2)
            server_ready = response.status_code == 200
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            server_ready = False

        if server_ready:
            log('Сервер Ollama уже работает; используем существующий сервер.')
        else:
            ollama_process = subprocess.Popen(
                [ollama_path, 'serve'],
                cwd=os.path.dirname(ollama_path),
                startupinfo=startupinfo,
                creationflags=creationflags,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            log('Ожидание ответа от ИИ-сервера...')
            for _ in range(30):
                if ollama_process.poll() is not None:
                    log('Ошибка: процесс Ollama завершился во время запуска.')
                    ollama_process = None
                    return False
                try:
                    response = requests.get('http://127.0.0.1:11434/', timeout=2)
                    if response.status_code == 200:
                        server_ready = True
                        break
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                    pass
                time.sleep(1)
                log('Ожидание ответа от ИИ-сервера...')

        if not server_ready:
            log('Ошибка: сервер Ollama не ответил за отведённое время.')
            stop_local_ollama()
            return False

        log('ИИ-движок успешно запущен и ответил.')
        log(f"Проверка локальной модели '{MODEL_NAME}'...")
        try:
            models_status = requests.get(
                'http://127.0.0.1:11434/api/tags', timeout=10
            ).json()
            downloaded_models = [
                model.get('name', '') for model in models_status.get('models', [])
            ]
        except Exception:
            downloaded_models = []

        if not any(MODEL_NAME in name for name in downloaded_models):
            log(f"Модель '{MODEL_NAME}' не найдена. Начинаю скачивание...")
            log('Это произойдет один раз при первом запуске программы.')
            log('Пожалуйста, подождите, скачивается модель...')
            try:
                with requests.post(
                    'http://127.0.0.1:11434/api/pull',
                    json={'name': MODEL_NAME},
                    stream=True,
                    timeout=(10, None)
                ) as pull_response:
                    if pull_response.status_code != 200:
                        log(
                            f'Не удалось скачать модель. '
                            f'Код ошибки: {pull_response.status_code}'
                        )
                        return False
                    for line in pull_response.iter_lines():
                        if line:
                            # out = str(line.decode('utf-8', errors='replace'))
                            log('[ЗАГРУЗКА МОДЕЛИ] ' + line.decode('utf-8', errors='replace'))
                    log(f"Модель '{MODEL_NAME}' скачана.")
            except Exception as e:
                log(f'Ошибка скачивания модели: {e}')
                return False
        else:
            log(f"Модель '{MODEL_NAME}' установлена и готова к работе")
        return True

    except Exception as e:
        log(f'Не удалось запустить ИИ-систему: {e}')
        stop_local_ollama()
        return False


def stop_local_ollama():
    global ollama_process
    with _ollama_stop_lock:
        process = ollama_process
        if process is None:
            return
        ollama_process = None
        if process.poll() is not None:
            return
        try:
            log('Выключение ИИ-движка...')
        except Exception:
            pass
        try:
            if os.name == 'nt':
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=8, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            try:
                log('ИИ-движок остановлен.')
            except Exception:
                pass
        except Exception as e:
            try:
                log(f'Ошибка при остановке Ollama: {e}')
            except Exception:
                pass


atexit.register(stop_local_ollama)

def ask_ai_model(system_instruction, user_text):
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,  
            messages=[
                {'role': 'system', 'content': system_instruction},
                {'role': 'user', 'content': user_text}
            ],
            temperature=0.3 
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f'Ошибка при отправке запроса к модели: {e}'


def get_clean_page_text(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        if response.status_code != 200: 
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        for el in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            el.extract()
        extracted_links = []
        for a_tag in soup.find_all('a', href=True):
            link_text = a_tag.get_text(strip=True)
            href = a_tag['href']
            if len(link_text) > 15 and not href.startswith('#') and 'javascript:' not in href:
                from urllib.parse import urljoin
                absolute_url = urljoin(url, href)
                link_string = f"Текст: '{link_text}', Ссылка: {absolute_url}"
                if link_string not in extracted_links:
                    extracted_links.append(link_string)
        return extracted_links
    except Exception:
        return []


def precheck_link_age(link_item):
    urls = re.findall(r'(https?://[^\s]+)', link_item)
    if not urls:
        return None
    url = urls[0].rstrip(")}].,;\\\"'")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            log(f'[ДАТА] HTTP {response.status_code}: {url}')
            return None

        response.encoding = response.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        published_at = extract_published_date(soup)

        if published_at is None:
            log(f'[ДАТА] Дата не найдена: {url}')
            return None

        if not is_news_recent(published_at):
            age = datetime.now(timezone.utc) - published_at
            reason = 'дата в будущем' if age < timedelta(0) else f'старше {MAX_NEWS_AGE_DAYS} дней'
            log(f'[ДАТА] ({reason}; дата: {published_at.isoformat()}): {url}')
            return None

        log(f'[ДАТА] Прошла предварительную проверку: {published_at.isoformat()} — {url}')
        return link_item
    except Exception as e:
        log(f'[ДАТА] Ошибка проверки {url}: {e}')
        return None


def check_single_link_ai(link_item):
    urls = re.findall(r'(https?://[^\s]+)', link_item)
    if not urls:
        return None
    current_url = urls[0].rstrip(')}].,;"\'')

    
    topics_str = ", ".join([f'"{t}"' for t in MY_TOPICS])

    system_prompt = f'''Ты — интеллектуальный новостной фильтр. 
    Твоя задача — определить, соответствует ли заголовок новости одной из следующих тем: {topics_str}.
    
    Правила:
    - Если заголовок четко относится хотя бы к ОДНОЙ из указанных тем, ответь СТРОГО словом: ДА.
    - Если заголовок не связан с этими темами (или это общая ссылка вроде 'Контакты', 'О нас', 'Политика'), ответь СТРОГО словом: НЕТ.
    
    Ответь одним словом ДА или НЕТ. Без знаков препинания и объяснений.'''

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f'Проанализируй строку:\n{link_item}'}
            ],
            temperature=0.1,
            max_tokens=5
        )
        ai_answer = completion.choices[0].message.content.strip().lower()
        if 'да' in ai_answer or 'yes' in ai_answer:
            log('Статья подходит тематически: ' + str(link_item).split('екст: ')[1].split(', С')[0])
            return current_url
        log('Статья не подходит тематически: ' + str(link_item).split('екст: ')[1].split(', С')[0])
    except Exception as e:
        log(f'[ОШИБКА ИИ] Не удалось проверить ссылку {current_url}: {e}')
    return None

def extract_published_date(soup):
    import json

    
    meta_selectors = [
        ('property', 'article:published_time'),
        ('name', 'article:published_time'),
        ('property', 'og:published_time'),
        ('name', 'datePublished'),
        ('name', 'publish-date'),
        ('name', 'pubdate'),
        ('name', 'date'),
        ('itemprop', 'datePublished'),
    ]
    for attr, value in meta_selectors:
        tag = soup.find('meta', attrs={attr: value})
        if tag:
            raw_date = tag.get('content') or tag.get('value')
            if raw_date:
                try:
                    parsed = date_parser.parse(raw_date)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed.astimezone(timezone.utc)
                except (ValueError, TypeError, OverflowError):
                    pass

    
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        raw_json = script.string or script.get_text()
        if not raw_json:
            continue
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            continue

        def walk_jsonld(obj):
            if isinstance(obj, dict):
                for key in ('datePublished', 'dateCreated'):
                    value = obj.get(key)
                    if isinstance(value, str):
                        try:
                            parsed = date_parser.parse(value)
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            return parsed.astimezone(timezone.utc)
                        except (ValueError, TypeError, OverflowError):
                            pass
                for value in obj.values():
                    found = walk_jsonld(value)
                    if found:
                        return found
            elif isinstance(obj, list):
                for value in obj:
                    found = walk_jsonld(value)
                    if found:
                        return found
            return None

        found_date = walk_jsonld(data)
        if found_date:
            return found_date

    
    for tag in soup.find_all('time'):
        raw_date = tag.get('datetime') or tag.get_text(' ', strip=True)
        if raw_date:
            try:
                parsed = date_parser.parse(raw_date, fuzzy=True)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (ValueError, TypeError, OverflowError):
                continue

    return None


def is_news_recent(published_at, max_age_days=MAX_NEWS_AGE_DAYS):
    if published_at is None:
        return False

    now = datetime.now(timezone.utc)
    age = now - published_at
    return timedelta(0) <= age <= timedelta(days=max_age_days)


def download_article_content(url, idx, total):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            log(f'[ДАТА] Пропуск {url}: HTTP {res.status_code}')
            return None

        res.encoding = res.apparent_encoding or 'utf-8'
        article_soup = BeautifulSoup(res.text, 'html.parser')
        published_at = extract_published_date(article_soup)

        for el in article_soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            el.extract()

        article_text = article_soup.get_text(separator=' ', strip=True)
        if len(article_text) < 150:
            log(f'Пропуск: текст статьи слишком короткий: {url}')
            return None

        title_tag = article_soup.find('h1')
        title = title_tag.get_text(' ', strip=True) if title_tag else (
            article_soup.title.get_text(' ', strip=True) if article_soup.title else url
        )

        log(f'Принята новость от {published_at.isoformat()}: {title}')
        return {
            'url': url,
            'title': title,
            'text': article_text[:3000],
            'published_at': published_at.isoformat()
        }
    except Exception as e:
        log(f'[ОШИБКА] Не удалось скачать/проверить статью {url}: {e}')
        return None


def _looks_mostly_english(text):
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum('a' <= ch.lower() <= 'z' for ch in letters)
    cyrillic = sum('\u0400' <= ch.lower() <= '\u052f' for ch in letters)
    return latin > 0 and latin > cyrillic * 1.5


def _summarize_one_article(article, index, total):
    title = str(article.get('title') or 'Заголовок не найден').strip()
    url = str(article.get('url') or '').strip()
    published_at = str(article.get('published_at') or 'Дата не указана').strip()
    article_text = str(article.get('text') or '').strip()[:4500]
    if not article_text:
        return None

    system_prompt = (
        'Ты — русскоязычный аналитик по информационной безопасности. '
        'Пиши ТОЛЬКО на русском языке. Английскими оставляй только имена собственные, '
        'названия продуктов, организаций, CVE и общепринятые технические термины. '
        'Не выдумывай сведения. Используй только текст статьи. '
        'Если сведений нет, прямо напиши «В источнике не указано». '
        'Не повторяй ссылку и дату: программа добавит их автоматически.'
    )
    user_prompt = f'''Сделай краткий, точный аналитический разбор ОДНОЙ статьи для руководителя ИБ.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
- Ответ полностью на русском языке.
- Не переводи имена собственные, названия организаций и продуктов.
- Не добавляй фактов, которых нет в тексте.
- Сохрани существенные даты, числа, суммы, названия систем и уязвимостей точно.
- Различай подтверждённые события и возможные риски.
- Не пиши общие рассуждения и длинное вступление.
- Используй ровно эти разделы, каждый с новой строки:
СУТЬ: (5-6 предложений о том, что произошло)
ЗАТРОНУТЫЕ: (организации, системы, продукты или «В источнике не указано»)
ПОСЛЕДСТВИЯ: (только описанные в статье последствия)
ВАЖНЫЕ ФАКТЫ: (ключевые даты (с кратким пояснением), числа и технические детали (с кратким пояснением))
ЗНАЧЕНИЕ ДЛЯ ИБ: (1–2 предложения, выводы должны опираться на статью)
АВТОР: (автор, если указан; иначе не пиши эту строчку)

ЗАГОЛОВОК: {title}
ТЕКСТ СТАТЬИ:
{article_text}'''

    for attempt in range(2):
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                temperature=0.1,
                max_tokens=750
            )
            summary = (completion.choices[0].message.content or '').strip()
            if summary and not _looks_mostly_english(summary):
                return (
                    f'## {index}. {title}\n'
                    f'Дата публикации: {published_at}\n'
                    f'Источник: {url or "Ссылка не указана во входных данных"}\n\n'
                    f'{summary}\n'
                )
            log(f'[ДАЙДЖЕСТ] Ответ не на русском, повтор запроса ({index}/{total}, попытка {attempt + 1})')
            user_prompt += '\n\nВАЖНО: предыдущий ответ не соответствовал языковому требованию. '
            user_prompt += 'Сгенерируй ответ заново ИСКЛЮЧИТЕЛЬНО на русском языке.'
        except Exception as e:
            log(f'[ДАЙДЖЕСТ] Ошибка обработки статьи {url}: {e}')
            break

    return (
        f'## {index}. {title}\n'
        f'Дата публикации: {published_at}\n'
        f'Источник: {url or "Ссылка не указана во входных данных"}\n\n'
        'Не удалось получить корректный русскоязычный пересказ от локальной модели.\n'
    )


def generate_final_top5_editorial(articles_data):
    if not articles_data:
        return 'Нет данных для анализа.'

    unique_articles = []
    seen_urls = set()
    for article in articles_data:
        url = str(article.get('url') or '').strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(article)
    if not unique_articles:
        return 'Нет статей с корректными ссылками.'
    cards = []
    for i, article in enumerate(unique_articles, 1):
        title = str(article.get('title') or 'Заголовок не найден').strip()
        text_excerpt = re.sub(r'\s+', ' ', str(article.get('text') or ''))[:450]
        cards.append(f'{i}. {title}\nФрагмент: {text_excerpt}')

    selection_system = (
        'Ты — редактор новостей по информационной безопасности. '
        'Выбери не более 5 наиболее значимых уникальных событий из списка. '
        'Ответь только номерами исходных статей через запятую, например: 2, 4, 7. '
        'Не пиши пояснений, заголовков или текста дайджеста. '
        'Если ни одна статья не подходит, ответь: НЕТ.'
    )
    selection_user = (
        f'Темы: {", ".join(MY_TOPICS)}.\n'
        'Приоритет: реальные киберинциденты, уязвимости, утечки, мошенничество, '
        'последствия для организаций и практически значимые меры защиты. '
        'Не выбирай общие страницы, дубли и материалы без содержательного события.\n\n'
        'СПИСОК СТАТЕЙ:\n' + '\n\n'.join(cards)
    )

    log(f'[ДАЙДЖЕСТ] Этап 1/2: выбор до 5 статей из {len(unique_articles)}')
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {'role': 'system', 'content': selection_system},
                {'role': 'user', 'content': selection_user}
            ],
            temperature=0.0,
            max_tokens=80
        )
        selection = (completion.choices[0].message.content or '').strip()
    except Exception as e:
        log(f'[ДАЙДЖЕСТ] Ошибка выбора статей: {e}')
        return f'Ошибка выбора статей: {e}'

    if 'НЕТ' in selection.upper() and not re.search(r'\d', selection):
        return 'Локальная модель не выбрала подходящих статей.'

    selected_numbers = []
    for match in re.findall(r'\d+', selection):
        number = int(match)
        if 1 <= number <= len(unique_articles) and number not in selected_numbers:
            selected_numbers.append(number)
        if len(selected_numbers) == 5:
            break
    if not selected_numbers:
        log(f'[ДАЙДЖЕСТ] Не удалось разобрать ответ модели: {selection!r}. Используются первые статьи как резерв.')
        selected_numbers = list(range(1, min(5, len(unique_articles)) + 1))

    selected_articles = [unique_articles[number - 1] for number in selected_numbers]
    log(f'[ДАЙДЖЕСТ] Выбрано статей: {len(selected_articles)}. Этап 2/2: отдельный пересказ каждой статьи')
    summaries = []
    total = len(selected_articles)
    for index, article in enumerate(selected_articles, 1):
        log(f'[ДАЙДЖЕСТ] Обработка статьи {index}/{total}: {article.get("title", "Без заголовка")}')
        summary = _summarize_one_article(article, index, total)
        if summary:
            summaries.append(summary)
    if not summaries:
        return 'Не удалось подготовить пересказ выбранных статей.'
    return '\n\n'.join(summaries)

def start(TARGET_SITES, lt):
    global log_text
    global is_running
    log_text = lt
    if not is_running:
        is_running = True
        try:
            if not start_local_ollama():
                log('Сбор отменён: Ollama не запустилась.')
                return
            log('Сбор ссылок с целевых сайтов')
            all_site_links = {}
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_url = {executor.submit(get_clean_page_text, url): url for url in TARGET_SITES}
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        links = future.result()
                        all_site_links[url] = links
                        log(f'{url}: Собрано {len(links)} потенциальных ссылок')
                    except Exception as e:
                        log(f'Ошибка сбора ссылок с {url}: {e}')
                
            
            
            log('Предварительная проверка возраста новостей')
            links_pool = []
            for url, links in all_site_links.items():
                links_pool.extend(links[:30]) 
            
            recent_links = []
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = executor.map(precheck_link_age, links_pool)
                for item in results:
                    if item:
                        recent_links.append(item)

            log(f'Свежих ссылок перед проверкой ИИ: {len(recent_links)}')
            log('Фильтрация ссылок по тематике через ИИ')
            news_urls_to_process = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                results = executor.map(check_single_link_ai, recent_links)
                for url in results:
                    if url and url not in news_urls_to_process:
                        news_urls_to_process.append(url)

            log(f'ИИ одобрил {len(news_urls_to_process)} тематических статей')

            
            collected_articles_content = []
            if news_urls_to_process:
                log('Скачивание текстов одобренных статей')
                total_news = len(news_urls_to_process)
                
                with ThreadPoolExecutor(max_workers=4) as executor:
                    future_to_article = {
                        executor.submit(download_article_content, url, idx, total_news): url 
                        for idx, url in enumerate(news_urls_to_process, 1)
                    }
                    for future in as_completed(future_to_article):
                        res = future.result()
                        if res:
                            collected_articles_content.append(res)
                            
                log(f'Успешно скачано текстов статей: {len(collected_articles_content)}')
                
                
                log('Анализ статей и подготовка дайджеста')
                final_digest = generate_final_top5_editorial(collected_articles_content)
                
                log('== ФИНАЛЬНЫЙ ДАЙДЖЕСТ ==')
                log(final_digest)
                output_dir = Path("output")
                output_dir.mkdir(parents=True, exist_ok=True)
                file_path = output_dir / ('digest-' + '{date:%Y-%m-%d-%H-%M-%S}'.format(date=datetime.now()) + '.json')
                file_path.write_text(final_digest, encoding="utf-8")
                os.startfile(file_path)
            else:
                log('Свежих тематических новостей не обнаружено.')
        finally:
            is_running = False
            stop_local_ollama()
