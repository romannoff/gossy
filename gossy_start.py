import re
from tools import Tools
import threading
import queue
import customtkinter as ctk
import pyperclip
import tkinter as tk
from logging_config import logger
import argparse


class App:
    """
    Класс реализует UI интерфейс и логику работы приложения
    """
    def __init__(self, root, view_browser=False):
        # Очередь, в которую помещаются результаты работы методов из класса Tools
        self.result_queue = queue.Queue()

        # Флаг, который активируется при нажатии на кнопку "Остановить"
        self.cancel_flag = threading.Event()

        # Модуль с методами для парсинга и соотнесения параметров
        self.tools = Tools(self.result_queue, self.cancel_flag, browser_window=view_browser)

        # Результаты работы методов из класса Tools хранятся здесь
        self.steps = {
            'citilink_query': '',
            'citilink_url': '',
            'goszakupki_query': '',
            'goszakupki_url': '',
        }

        # Характеристики с сайта ситилинк
        self.citilink_characters = None

        # Характеристики с сайта госзакупки
        self.goszakupki_characters = None

        # Список, соотносящий характеристики из ситилинка характеристикам из госзакупок, вида
        # [(char_citilink_id, char_goszakupki_id), ...]
        self.matches = None

        # Основное окно
        self.root = root
        self.root.title("Поиск товаров")
        self.root.geometry("800x700")

        # Настройка темы и внешнего вида
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        bg_color = root.cget("fg_color")

        # Единый scrollable_frame для всего приложения
        self.scrollable_frame = ctk.CTkScrollableFrame(
            master=root,
            width=780,
            height=680,
            fg_color=bg_color,
            scrollbar_button_color=bg_color,
            corner_radius=0,
            scrollbar_button_hover_color="#3a3a3a"
        )
        self.scrollable_frame.pack(pady=0, padx=0, fill="both", expand=True)

        self.label = ctk.CTkLabel(master=self.scrollable_frame, text="Поиск", font=("Arial", 16))
        self.label.pack(pady=20)

        # Поле для ввода запроса
        self.search_entry = ctk.CTkEntry(
            master=self.scrollable_frame,
            placeholder_text="Введите запрос",
            width=300,
            height=40
        )
        self.search_entry.pack(pady=5)
        self.search_entry.bind("<Return>", self.main_button_command)

        self.buttons_frame = ctk.CTkFrame(
            master=self.scrollable_frame,
            fg_color='transparent'
        )
        self.buttons_frame.pack(pady=2)

        # Кнопка СТОП \ ПРОДОЛЖИТЬ
        self.main_button = ctk.CTkButton(
            master=self.buttons_frame,
            text="Поиск",
            command=self.main_button_command,
            hover=True
        )
        self.main_button.grid(row=0, column=0, pady=5, padx=5, sticky="ew")

        self.clear_button = ctk.CTkButton(
            master=self.buttons_frame,
            text="Очистить",
            command=self.clear_button_command,
            hover=True
        )
        self.clear_button.grid(row=0, column=1, pady=5, padx=5, sticky="ew")

        # Статус
        self.current_operation = ctk.CTkLabel(
            master=self.scrollable_frame,
            text='',
            font=("Roboto", 12),
            height=32
        )
        self.current_operation.pack(pady=2)
        self.current_text = ''

        # Контейнер для результатов (изначально скрыт)

        self.frames: dict[str, ctk.CTkFrame | ctk.CTkLabel | ctk.CTkButton | None] = {
            'result_frame': None,
            'goszakupki_links': None,
            'goszakupki_frame': None,
            'columns_container': None,
            'copy_button': None,
            'copy_text': None
        }
        # Если не удаётся найти неукрупнённую позицию, то здесь будут храниться все неукрупнённые позиции для товара
        # пользователю должен будет выбрать необходимую позицию
        self.gz_links = None

        # Автоматически проставленные характеристики
        self.selected_values = {}

        self.gu_buttons_deactivate = False
        self.is_resizable = True
        self.in_work = False

        # Интерактивность
        self.current_state = 0
        self.wave = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

        # Проверка очереди
        self.check_queue()

    def clear_button_command(self, idx=0):
        """
        Работа кнопки "Очистить"
        :param idx: индекс фрейма, с которого начнётся очистка приложения.
        :return: None
        """
        # Если идут вычисления, то кнопка неактивна
        if self.in_work:
            return

        # Очистка фреймов
        for key in list(self.frames.keys())[idx:]:
            if self.frames[key] is not None:
                self.frames[key].destroy()
                self.frames[key] = None

        # Включаем возможность изменения размера окна
        if not self.is_resizable:
            self.root.resizable(True, True)
            self.is_resizable = True

        # Сбрасываем состояние флага отмены
        self.cancel_flag.clear()
        self.steps = {
            'citilink_query': '',
            'citilink_url': '',
            'goszakupki_query': '',
            'goszakupki_url': '',
        }

    def main_button_command(self, event=None):
        """
        Нажатие на кнопку запуска / прекращения поиска.
        Если вычисления не проводятся, то кнопка имеет подпись "Поиск",
        Иначе "Остановить".
        :return: None
        """
        current_text = self.main_button.cget("text")

        # Нажата кнопка с текстом "Поиск"
        if current_text == 'Поиск':
            self.cancel_flag.clear()
            search_input = self.search_entry.get()

            if search_input != '':
                self.main_button.configure(text="Остановить")

                if self.steps['citilink_query'] != search_input:
                    self.clear_button_command()
                    self.start_citilink_search(search_input)
                elif self.frames['result_frame'] is not None \
                        and self.steps['citilink_url'] != (url := self.frames['result_frame'].url_value.get()):
                    self.clear_button_command()
                    self.start_citilink_parsing(url)
                elif self.frames['goszakupki_frame'] is not None \
                        and self.steps['goszakupki_url'] != (url := self.frames['goszakupki_frame'].url_value.get()):
                    self.gu_buttons_deactivate = True
                    self.clear_button_command(idx=2)
                    self.start_goszakupki_parsing(url)
                else:
                    self.main_button.configure(text="Поиск")

        # Нажата кнопка с текстом "Остановить"
        if current_text == 'Остановить':
            self.main_button.configure(text="...")
            self.current_text = "Остановка. . ."
            self.cancel_flag.set()
            if not self.in_work:
                self.main_button.configure(text="Поиск")

    def start_citilink_search(self, search_name):
        """
        Запуск потока, ищущего URL товара по имени
        search_name: str - имя на товар
        :return:
        """
        self.in_work = True
        self.current_text = "Шаг 1 из 4.\nИщу товар на сайте Ситилинк. . ."
        self.clear_button_command()

        self.steps['citilink_query'] = search_name

        computation_thread = threading.Thread(target=self.tools.get_citilink_url, args=(search_name,))
        computation_thread.daemon = True  # Поток завершится при закрытии приложения
        computation_thread.start()

    def start_citilink_parsing(self, product_url):
        """
        Запуск потока, проводящего парсинг сайта ситилинк
        product_url: str - URL на товар
        :return: None
        """
        self.in_work = True
        self.current_text = "Шаг 2 из 4.\nСобираю характеристики с сайта Ситилинк. . ."
        self.clear_button_command()

        self.steps['citilink_url'] = product_url

        computation_thread = threading.Thread(target=self.tools.citilink_parsing, args=(product_url,))
        computation_thread.daemon = True  # Поток завершится при закрытии приложения
        computation_thread.start()

    def start_goszakupki_search(self, search_name):
        """
        Запуск потока, ищущего неукрупнённую позиции госзакупки
        :param search_name: str - Название товара
        :return: None
        """
        self.in_work = True
        self.current_text = "Шаг 3 из 4.\nИщу товар на сайте гос. закупки. . ."

        computation_thread = threading.Thread(target=self.tools.get_goszakupki_links,
                                              args=(search_name, self.citilink_characters))
        computation_thread.daemon = True  # Поток завершится при закрытии приложения
        computation_thread.start()

    def start_goszakupki_parsing(self, goszakupki_ref):
        """
        Запуск потока для парсинга госзакупок + происходит связывание характеристик
        с сайта ситилинк и характеристик ссайта госзакупки.
        :param goszakupki_ref: ссылка на неукрупнённую позицию.
        :return: None
        """
        self.in_work = True
        self.current_text = "Шаг 4 из 4.\nРасставляю значения характеристик. . ."

        computation_thread = threading.Thread(target=self.tools.match_params,
                                              args=(self.citilink_characters, goszakupki_ref))
        computation_thread.daemon = True  # Поток завершится при закрытии приложения
        computation_thread.start()

    def show_search_result(self, model_name, price, url):
        """
        Вывод результатов парсинга сайта ситилинк.
        :param model_name: str - Название товара
        :param price: str - Цена товара
        :param url: str - Ссылка на товар
        :return: None
        """
        self.current_text = "Шаг 2 из 4.\nВывожу результат..."
        self.clear_button_command()

        # Создаём новый фрейм для результатов
        result_frame = ctk.CTkFrame(
            master=self.scrollable_frame,
            fg_color="#2B2B2B",
            corner_radius=10,
            width=500,
        )
        result_frame.pack(pady=10, padx=200, fill="x")

        # --- Настройка сетки ---
        # Первый столбец — метки (минимальный вес), второй — поля (максимальный вес)
        result_frame.grid_columnconfigure(0, weight=0, minsize=100)
        result_frame.grid_columnconfigure(1, weight=1)

        # Метки и значения
        model_label = ctk.CTkLabel(
            master=result_frame,
            text="Модель:",
            font=("Roboto", 12),
        )
        model_label.grid(row=0, column=0, pady=5, padx=(10, 5), sticky="w")

        model_value = ctk.CTkTextbox(
            master=result_frame,
            font=("Roboto", 12, "bold"),
            fg_color="transparent",
            height=30,
            wrap="none"
        )
        model_value.grid(row=0, column=1, pady=5, padx=(5, 10), sticky="ew")
        model_value.insert("0.0", model_name.split(',')[0])
        model_value.configure(state="disabled")

        price_label = ctk.CTkLabel(
            master=result_frame,
            text="Цена:",
            font=("Roboto", 12),
        )
        price_label.grid(row=1, column=0, pady=5, padx=(10, 5), sticky="w")

        price_value = ctk.CTkTextbox(
            master=result_frame,
            font=("Roboto", 12, "bold"),
            fg_color="transparent",
            height=30,
            wrap="none"
        )
        price_value.grid(row=1, column=1, pady=5, padx=(5, 10), sticky="ew")
        price_value.insert("0.0", price)
        price_value.configure(state="disabled")

        url_label = ctk.CTkLabel(
            master=result_frame,
            text="URL:",
            font=("Roboto", 12),
        )
        url_label.grid(row=2, column=0, pady=5, padx=(10, 5), sticky="w")

        # Фрейм для ввода + кнопки
        input_frame = ctk.CTkFrame(
            master=result_frame,
            fg_color="transparent"
        )
        input_frame.grid(row=2, column=1, pady=5, padx=(5, 10), sticky="ew")

        input_frame.grid_columnconfigure(0, weight=1)
        input_frame.grid_columnconfigure(1, weight=0)

        url_value = ctk.CTkEntry(
            master=input_frame,
            height=40
        )
        url_value.insert(0, url)

        url_value.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        url_value.bind("<Return>", lambda e: self.start_citilink_parsing(url_value.get()))
        result_frame.url_value = url_value

        paste_button = ctk.CTkButton(
            master=input_frame,
            text="Вставить",
            width=80,
            height=40,
            command=lambda: self.paste_from_clipboard(url_value)
        )
        paste_button.grid(row=0, column=1)

        self.frames['result_frame'] = result_frame

    @staticmethod
    def paste_from_clipboard(input_frame):
        """
        Функция для вставки текста из буфера копирования
        :param input_frame: Фрейм, куда вставится текст
        :return: None
        """
        clipboard_text = pyperclip.paste()
        input_frame.delete(0, "end")  # Очищаем текущее содержимое
        input_frame.insert(0, clipboard_text)  # Вставляем текст из буфера

    def show_gu_search_result(self, page_name, link):
        """
        Выводим результат парсинга Госзакупок в едином стиле со Citilink
        :param page_name: название закупки
        :param link: ссылка на страницу закупки
        """
        self.current_text = "Шаг 3 из 4.\nВывожу результат..."
        self.clear_button_command(idx=2)

        # Создаём новый фрейм для результата
        result_frame = ctk.CTkFrame(
            master=self.scrollable_frame,
            fg_color="#2B2B2B",
            corner_radius=10,
            width=500,
        )
        result_frame.pack(pady=10, padx=200, fill="x")

        # Настройка сетки
        result_frame.grid_columnconfigure(0, weight=0, minsize=100)
        result_frame.grid_columnconfigure(1, weight=1)

        # --- Название закупки ---
        goszak_label = ctk.CTkLabel(
            master=result_frame,
            text="Госзакупки:",
            font=("Roboto", 12),
        )
        goszak_label.grid(row=0, column=0, pady=5, padx=(10, 5), sticky="w")

        goszak_value = ctk.CTkTextbox(
            master=result_frame,
            font=("Roboto", 12, "bold"),
            fg_color="transparent",
            height=30,
            wrap="none"
        )
        goszak_value.grid(row=0, column=1, pady=5, padx=(5, 10), sticky="ew")
        goszak_value.insert("0.0", page_name)
        goszak_value.configure(state="disabled")

        # --- Ссылка закупки ---
        url_label = ctk.CTkLabel(
            master=result_frame,
            text="URL:",
            font=("Roboto", 12),
        )
        url_label.grid(row=1, column=0, pady=5, padx=(10, 5), sticky="w")

        # Фрейм для ввода + кнопки
        input_frame = ctk.CTkFrame(
            master=result_frame,
            fg_color="transparent"
        )
        input_frame.grid(row=1, column=1, pady=5, padx=(5, 10), sticky="ew")

        input_frame.grid_columnconfigure(0, weight=1)
        input_frame.grid_columnconfigure(1, weight=0)

        url_entry = ctk.CTkEntry(
            master=input_frame,
            height=40
        )
        url_entry.insert(0, link)
        url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        result_frame.url_value = url_entry

        url_entry.bind("<Return>", lambda e: self.start_goszakupki_parsing(url_entry.get()))

        paste_button = ctk.CTkButton(
            master=input_frame,
            text="Вставить",
            width=80,
            height=40,
            command=lambda: self.paste_from_clipboard(url_entry)
        )
        paste_button.grid(row=0, column=1)

        # Сохраняем ссылку на фрейм
        self.frames['goszakupki_frame'] = result_frame

    def gz_link_click(self, correct_ref, correct_name):
        """
        Функция для обработки выбора пользователем неукрупнённой позиции.
        :param correct_ref: Выбранная ссылка
        :param correct_name: Выбранное имя позиции
        :return: None
        """
        if not self.gu_buttons_deactivate:
            logger.debug('Выбрана не укрупнённая позиция: %s, url: %s' % (correct_ref, correct_name))
            self.show_gu_search_result(correct_name, correct_ref)
            self.start_goszakupki_parsing(correct_ref)
            self.gu_buttons_deactivate = True

    def show_gz_links(self, category):
        """
        Показываем неукрупнённые позиция товара, чтобы пользователь сам выбрал необходимую.
        :param category: str - Название категории, по которой выбирается неукрупнённая позиция.
        :return: None
        """

        # Информация о госзакупках
        self.current_text = "Шаг 3 из 4.\nЖду ответа от пользователя. . ."

        self.clear_button_command(idx=1)

        goszakupki_links = ctk.CTkFrame(
            master=self.scrollable_frame,
            width=500,
            fg_color="#2B2B2B",
            corner_radius=10
        )
        goszakupki_links.pack(pady=10, padx=200, fill="x")

        # Поле Госзакупки
        goszakupki_label = ctk.CTkTextbox(
            master=goszakupki_links,
            font=("Roboto", 12),
            fg_color="transparent",
            height=30,
            width=150,
            wrap="none",
        )
        goszakupki_label.pack(pady=5, padx=10, fill="x")
        goszakupki_label.insert("0.0", f"Выберите {category}:", )
        goszakupki_label.configure(state="disabled")

        for key in self.gz_links:
            ref, name = self.gz_links[key]
            button = ctk.CTkButton(
                master=goszakupki_links,
                text=key,
                command=lambda ref_=ref, name_=name: self.gz_link_click(ref_, name_),
                hover=True
            )
            button.pack(pady=5, padx=10, fill="x")

        self.frames['goszakupki_links'] = goszakupki_links

    def show_columns_container(self):
        """
        Вывод характеристик с сайта ситилинк и с сайта госзакупки.
        :return: None
        """
        self.current_text = "Шаг 4 из 4.\nВывожу результат. . ."

        self.clear_button_command(idx=3)

        self.is_resizable = False
        self.root.resizable(False, False)

        columns_container = ctk.CTkFrame(
            master=self.scrollable_frame,
            fg_color="transparent",
        )

        columns_container.pack(fill='x')

        # Создаем первый фрейм (СИТИЛИК)
        citilink_container = ctk.CTkScrollableFrame(
            master=columns_container,
            corner_radius=0,
            height=600,
            fg_color="#2B2B2B"
        )

        citilink_container.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        label1 = ctk.CTkLabel(master=citilink_container, text="СИТИЛИК", font=("Arial", 16))
        label1.pack(pady=10, padx=10, fill="x", expand=False)

        # Создаем второй фрейм (ГОСЗАКУПКИ)
        goszakupki_container = ctk.CTkScrollableFrame(
            corner_radius=0,
            height=600,
            master=columns_container,
            fg_color="#2B2B2B"
        )
        goszakupki_container.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        label2 = ctk.CTkLabel(master=goszakupki_container, text="ГОСЗАКУПКИ", font=("Arial", 16))
        label2.pack(pady=20)

        columns_container.grid_columnconfigure(0, weight=3)
        columns_container.grid_columnconfigure(1, weight=4)

        self.frames['columns_container'] = columns_container

        # Отображаем все характеристики Ситилинка
        for i, char in enumerate(self.citilink_characters.items()):
            self.new_citilink_params(citilink_container, {'name': char[0], 'value': char[1]}, i, goszakupki_container)

        # Отображаем все характеристики Госзакупок
        for i, char in enumerate(self.goszakupki_characters):
            self.new_goszakupki_params(goszakupki_container, char, i, citilink_container)

        self.current_text = "Поиск завершён!"
        self.main_button.configure(text="Поиск")

        copy_button = ctk.CTkButton(
            master=self.scrollable_frame,
            text="Копировать характеристики",
            command=self.copy_chars,
            hover=True
        )
        copy_button.pack(pady=10, fill='x', padx=40)
        self.frames['copy_button'] = copy_button

        copy_text = ctk.CTkLabel(
            master=self.scrollable_frame,
            text='',
            font=("Roboto", 12),
            height=16,
            text_color=("black", "white")
        )
        copy_text.pack(pady=(0, 15))
        self.frames['copy_text'] = copy_text

        # Поиск завершён
        self.in_work = False
        self.gu_buttons_deactivate = False

    def copy_chars(self):
        """
        Обработка нажатия на кнопку "Копировать"
        :return: None
        """
        self.tools.copy_chars()
        self.frames['copy_text'].configure(text='Характеристики скопированы')
        self.frames['copy_text'].configure(text_color=("black", "white"))
        self.root.after(2000, self.fade_text, self.frames['copy_text'])

    def fade_text(self, label, steps=60, interval=5):
        """
        Функция для затухающего текста.
        """
        current_mode = ctk.get_appearance_mode()
        start_color = self.tools.get_effective_color(label.cget("text_color"), current_mode, label)
        end_color = self.tools.get_effective_color(label.master.cget("fg_color"), current_mode, label)

        def step(current_step):
            if current_step > steps:
                return
            t = current_step / steps
            new_color = self.tools.interpolate_color(start_color, end_color, t)
            label.configure(text_color=new_color)
            label.after(interval, step, current_step + 1)

        step(0)

    def new_citilink_params(self, main_frame, char, idx, neighbour_frame):
        """
        Добавляем строку в столбец с характеристиками ситилинка
        :param main_frame: Фрейм, куда вставляется характеристика
        :param char: str - Название характеристики
        :param idx: int - Индекс характеристики
        :param neighbour_frame: Фрейм с характеристиками с сайта госзакупки
        :return: None
        """
        # Создаем дочерний фрейм
        child_frame = ctk.CTkFrame(
            master=main_frame,
            fg_color="#222222",
            corner_radius=10,
        )
        child_frame.pack(pady=10, padx=10, fill="x", expand=False)  # expand=False предотвращает растяжение

        # Название характеристики
        name_label = ctk.CTkTextbox(
            master=child_frame,
            font=("Arial", 14, "bold"),
            fg_color="transparent",
            wrap="none",
            height=20,  # Минимальная высота
        )
        name_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        name_label.insert("0.0", char["name"])
        name_label.configure(state="disabled")

        # Значение характеристики
        value_label = ctk.CTkTextbox(
            master=child_frame,
            font=("Arial", 14),
            fg_color="transparent",
            wrap="none",
            height=20,  # Минимальная высота
        )
        value_label.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        value_label.insert("0.0", char["value"])
        value_label.configure(state="disabled")

        gz_category = None
        command = None

        for match in self.matches:
            if match[0] == idx:
                gz_category_id = match[1]
                gz_category = self.goszakupki_characters[gz_category_id]['name']
                fraction = max((gz_category_id - 1) / len(self.goszakupki_characters), 0)

                def command(fraction_=fraction):
                    self.scroll_to(neighbour_frame, fraction_)

        # Вторая строка: текстовое поле
        textbox = ctk.CTkButton(
            master=child_frame,
            text='🔗 ' + gz_category if gz_category is not None else ' '*10,
            state='normal' if gz_category is not None else 'disabled',
            height=20,
            anchor="w",
            command=command if command is not None else lambda: ...,
            fg_color=('white', '#151515'),
            hover=False,
            font=("Arial", 12)
        )
        textbox.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Настраиваем вес столбцов для адаптивности по горизонтали
        child_frame.grid_columnconfigure(0, weight=1)
        child_frame.grid_columnconfigure(1, weight=2)

        # Отключаем растяжение строк
        child_frame.grid_rowconfigure(0, weight=0)
        child_frame.grid_rowconfigure(1, weight=0)

    def new_goszakupki_params(self, main_frame, char, idx, neighbour_frame):
        """
        Добавляем строку в столбец с характеристиками госзакупок
        :param main_frame: Фрейм, куда вставляется характеристика
        :param char: str - Название характеристики
        :param idx: int - Индекс характеристики
        :param neighbour_frame: Фрейм с характеристиками с сайта ситилинк
        :return: None
        """
        child_frame = ctk.CTkFrame(
            master=main_frame,
            fg_color="#222222",
            height=60,
        )
        child_frame.pack(pady=10, padx=10, fill="x")

        name_label = ctk.CTkTextbox(
            master=child_frame,
            font=("Arial", 14),
            fg_color="transparent",
            wrap="none",
            height=40
        )
        name_label.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        name_label.insert("0.0", char["name"])
        name_label.configure(state="disabled")

        button_frame = ctk.CTkScrollableFrame(
            master=child_frame,  # Родительский фрейм
            fg_color="transparent",  # Прозрачный фон
            orientation="horizontal",  # Вертикальная прокрутка
            corner_radius=0,
            height=40  # Высота фрейма (можно настроить)
        )
        button_frame.grid(row=0, column=1, padx=10, pady=5, sticky="nsew")

        # Добавляем радиокнопки
        for i, value in enumerate(char["values"]):
            radio_button = ctk.CTkRadioButton(
                master=button_frame,
                text=value,
                value=value,
                variable=self.selected_values[char["name"]],
                command=lambda c=char["name"]: self.update_selection(c)
            )
            radio_button.grid(row=0, column=i, padx=10, pady=5, sticky="nsew")

        command = None

        for match in self.matches:
            if match[1] == idx:
                citilink_category_id = match[0]
                fraction = max((citilink_category_id - 1) / len(self.citilink_characters), 0)

                def command(fraction_=fraction):
                    self.scroll_to(neighbour_frame, fraction_)

        # Вторая строка: текстовое поле
        textbox = ctk.CTkButton(
            master=child_frame,
            text='🔗 ' + char["description"] if command is not None else ' '*10,
            height=20,
            anchor="w",
            fg_color=('white', '#151515'),
            hover=False,
            command=command if command is not None else lambda: ...,
            state='normal' if command is not None else 'disabled',
            font=("Arial", 12)
        )

        textbox.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")

        child_frame.grid_columnconfigure(0, weight=1)
        child_frame.grid_columnconfigure(1, weight=3)

        child_frame.grid_rowconfigure(0, weight=2)
        child_frame.grid_rowconfigure(1, weight=1)

    def get_url(self, char_name, char_value):
        for char in self.goszakupki_characters:
            if char['name'] == char_name:
                return char['refs'][char_value]

    def update_selection(self, char_name):
        """Обновляет выбор при смене радиокнопки"""
        url = self.get_url(char_name, self.selected_values[char_name].get())
        self.tools.click_url(url)
        logger.debug("Выбрано для %s значение %s" % (char_name, self.selected_values[char_name].get()))

    def get_match(self):
        """
        Формирование связей между характеристиками
        :return: None
        """
        self.matches = []

        citilink_categories = list(self.citilink_characters.keys())

        for gz_id, gz_chars in enumerate(self.goszakupki_characters):
            citilink_category = gz_chars['description']
            if citilink_category != '':
                citilink_id = citilink_categories.index(citilink_category)
                self.matches.append((citilink_id, gz_id))

    @staticmethod
    def scroll_to(parent_scrollable_frame, fraction):
        """
        Функция для прокрутки фрейма до выбранной характеристики.
        :param parent_scrollable_frame: Фрейм, который нужно прокрутить.
        :param fraction: Позиция, до которой нужно прокрутить фрейм.
        :return:
        """
        canvas: tk.Canvas = parent_scrollable_frame.parent_canvas
        canvas.yview_moveto(min(fraction, 1))

    def check_queue(self):
        """
        Функция проверяет очередь, в которую приходят результаты вычислений, и запускает следующие
        вычисления и отрисовки результатов.
        :return: None
        """
        try:
            if self.in_work and self.current_text != '':
                if type(self.current_text) is str:
                    self.current_text = self.current_text.split('\n')

                text = self.wave[self.current_state] + '\t' + self.current_text[0] + '\t' + self.wave[self.current_state] \
                       + '\n' + self.current_text[1]
                self.current_operation.configure(text=text)
                self.current_state = (self.current_state + 1) % len(self.wave)
            elif not self.in_work and self.current_text != '':
                self.current_operation.configure(text='')
                self.current_state = 0

            # Проверка очереди на наличие результата
            status, stage, results = self.result_queue.get_nowait()
            logger.debug('%s, %s, %s' % (status, stage, results))

            # Нажатие на кнопку "Остановить"
            if self.cancel_flag and self.cancel_flag.is_set():
                self.current_text = ""
                self.main_button.configure(text="Поиск")

            elif status == 'success':

                # Найдена ссылка на товар на сайте ситилинк
                if stage == 'citilink_search':
                    self.start_citilink_parsing(results)

                # Найдены характеристики на сайте ситилинк
                if stage == 'citilink_parsing':
                    product_name, product_price, characters = results

                    goszakupki_search = re.findall(r'[а-я ]+', product_name.lower())[0].strip()
                    self.steps['goszakupki_query'] = goszakupki_search

                    self.citilink_characters = characters
                    self.show_search_result(product_name, product_price, self.steps['citilink_url'])

                    self.start_goszakupki_search(goszakupki_search)

                # Найдена ссылка на неукрупнённую позицию на сайте госзакупки
                elif stage == 'goszakupki_search':
                    correct_ref, correct_name = results
                    self.steps['goszakupki_url'] = correct_ref

                    self.show_gu_search_result(correct_name, correct_ref)
                    self.start_goszakupki_parsing(correct_ref)

                # Найдены характеристики на сайте госзакупки
                elif stage == 'goszakupki_parsing':
                    self.goszakupki_characters = results
                    self.get_match()

                    self.selected_values = {
                        char["name"]: ctk.StringVar(value=char["default_value"])
                        for char in results
                    }

                    self.show_columns_container()

            elif status == 'fail':

                # Найти укрупнённую позицию не удалось -> пользователь должен её выбрать сам
                if stage == 'goszakupki_search':
                    category, exact_products_dict = results

                    self.gz_links = exact_products_dict

                    self.show_gz_links(category)

        except queue.Empty:
            pass
        # Периодический вызов через 500 мс
        self.root.after(500, self.check_queue)


if __name__ == "__main__":
    root = ctk.CTk()
    root.geometry("800x700")

    parser = argparse.ArgumentParser(description='Данная программа создана для автоматизации работы с госзакупками')

    parser.add_argument('-v', '--view-browser',
                        action='store_true',
                        help='Если аргумент задан, то будет открыт браузер для просмотра результатов работы. Иначе браузер будет работать в фоновом режиме')

    args = parser.parse_args()

    app = App(root, view_browser=True)
    root.mainloop()
