from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from selenium.webdriver.chrome.options import Options
import re
import numpy as np
from selenium.webdriver import ActionChains

import queue
from embeddings_model import EmbedChunks
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from logging_config import logger


class Tools:
    def __init__(self, results_queue, cancel_flag, browser_window=False):
        options = Options()
        if not browser_window:
            options.add_argument("--headless")  # работа без открытия браузера
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--enable-experimental-web-platform-features")

        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 11.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )

        self.driver = webdriver.Chrome(options=options)

        # уходим от флага --disable-features=IsolateOrigins, если он где-то добавлен
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
              Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
            '''
        })

        # даём сайту разрешения на работу с буфером
        self.driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {
                "origin": "https://moy-zakupki.ru",
                "permissions": [
                    "clipboardReadWrite",
                    "clipboardSanitizedWrite"
                ]
            }
        )
        self.results_queue: queue.Queue = results_queue
        self.cancel_flag = cancel_flag
        self.get_embedding = EmbedChunks('intfloat/multilingual-e5-small')

    def check_cancelled(self):
        if self.cancel_flag and self.cancel_flag.is_set():
            return True
        return False

    def click_url(self, url):
        self.driver.execute_script("arguments[0].click();", url)

    def get_citilink_url(self, product_name):
        """
        Находим URL товара на ситилинк по имени
        :param product_name: str - имя товара
        :return: str - URL товара
        """

        if self.check_cancelled():
            self.results_queue.put(('stopped', 'get_citilink_url', ''))
            return

        logger.info('Ищу url товара на citilink по запросу: %s' % product_name)

        self.driver.get(f"https://www.citilink.ru/search/?text={product_name}")

        product = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//div[@data-meta-name="SnippetProductVerticalLayout"]/a[1]'))
        )
        url = product.get_attribute('href')

        self.results_queue.put(('success', 'citilink_search', url))

    def citilink_parsing(self, product_url):
        """
        Находим товар на ситилинк, парсим характеристики.
        Возвращает Имя, Цену и Словарь {"название_характеристики: значение"}
        """

        logger.info('Получаю характеристики на сайте citilink по ссылке %s' % product_url)

        if self.check_cancelled():
            self.results_queue.put(('stopped', 'citilink_parsing', ''))
            return

        self.driver.get(product_url)

        name = self.driver.find_element(by=By.XPATH, value="//h1").text
        price = self.driver.find_element(by=By.XPATH, value='//div[@data-meta-name="PriceBlock__price"]').text

        search_button = self.driver.find_element(by=By.XPATH, value="//button[.//text()='Все характеристики']")

        while True:
            self.driver.execute_script("window.scrollBy(0,100)", "")
            time.sleep(0.5)
            try:
                search_button.click()
            except Exception as e:
                continue
            break

        parameters = {}

        params_name = []
        param_value = []

        ul_elements = WebDriverWait(self.driver, 10).until(
            EC.presence_of_all_elements_located((By.XPATH, "//ul[li/div/div and li/div/span]"))
        )

        # ul_elements = self.driver.find_elements(By.XPATH, "//ul[li/div/div and li/div/span]")

        # Извлечение текста из <div> и <span> внутри каждого <li>
        for ul in ul_elements:
            # Находим все <li> внутри <ul>
            li_elements = ul.find_elements(By.XPATH, ".//li")
            for li in li_elements:
                # Извлекаем текст из <div> внутри <div>
                div_text = li.find_elements(By.XPATH, ".//div/div")
                for div in div_text:
                    if div.text:
                        params_name.append(div.text)

                # Извлекаем текст из <span> внутри <div>
                span_text = li.find_elements(By.XPATH, "./div/span")
                for span in span_text:
                    if span.text:
                        param_value.append(span.text)

        for name_, value in zip(params_name, param_value):
            parameters[name_] = value

        self.results_queue.put(('success', 'citilink_parsing', [name, price, parameters]))

    def get_goszakupki_links(self, product_name, choice_params):
        """
        Поиск укрупнённой позиции + возврат не укрупнённой
        :param product_name:
        :param choice_params:
        :return:
        """
        if self.check_cancelled():
            self.results_queue.put(('stopped', 'get_goszakupki_links', ''))
            return

        logger.info('Ищу укрупнённую позицию товара на сайте госзакупки по запросу %s' % product_name)

        self.driver.get("https://moy-zakupki.ru//")

        search_input = self.driver.find_element(by=By.CLASS_NAME, value='n-input__input-el')
        search_input.send_keys(product_name)

        search_button = self.driver.find_elements(by=By.CLASS_NAME, value='n-button')
        search_button[0].click()

        product = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//div[div[@class="sm:flex justify-between"]]//a'))
        )
        # product = self.driver.find_elements(by=By.XPATH, value='//div[div[@class="sm:flex justify-between"]]//a')[0]
        product_link = product.get_attribute('href')

        if self.check_cancelled():
            self.results_queue.put(('stopped', 'get_goszakupki_links', ''))
            return

        self.driver.get(product_link)

        search_button = self.driver.find_element(by=By.XPATH, value='//button[.//span[text()="Уточните код КТРУ"]]')
        search_button.click()

        time.sleep(2)

        margin = self.driver.find_elements(by=By.XPATH, value='//li[@class="hover:text-sky-500 mb-2"]')[-1]
        margin = margin.get_attribute('style')[:-1]

        exact_products = self.driver.find_elements(by=By.XPATH, value=f'//li[@style="{margin}"]/a')

        exact_products_dict = {}
        category = None

        for exact_product in exact_products[1:]:
            exact_product_ref = exact_product.get_attribute('href')
            exact_product_name = exact_product.text

            cat = re.search(r'\((.*)\:(.*)\)', exact_product_name)
            exact_products_dict[cat[2]] = [exact_product_ref, exact_product_name]

            if category is None:
                category = cat[1]

        embedded_dict = {}

        logger.debug('choice_params:\n%s' % str(choice_params))

        for key in choice_params.keys():
            embed = self.get_embedding([key])['embeddings'][0]
            embedded_dict[key] = embed

        res = self.get_embedding.get_nearest(category, embedded_dict)

        category_value = choice_params[res[0]]

        # сначала ищем точное совпадение
        if category_value in list(exact_products_dict.keys()):
            correct_ref, correct_name = exact_products_dict[category_value]
            self.results_queue.put(('success', 'goszakupki_search', [correct_ref, correct_name]))
        elif (match := re.search(r'\d+', category_value)) is not None:
            category_value = float(match[0])

            delta = []

            for key, value in exact_products_dict.items():
                key = key.strip().split()
                if key[0] in ['≤', '≥', '<', '>']:
                    sign, number = key
                    number = float(number)
                    category_value = float(category_value)

                    if sign == '≤' and category_value <= number:
                        delta.append(number - category_value)
                    elif sign == '<' and category_value < number:
                        delta.append(number - category_value)
                    elif sign == '≥' and category_value >= number:
                        delta.append(category_value - number)
                    elif sign == '>' and category_value > number:
                        delta.append(category_value - number)
                    else:
                        delta.append(np.inf)

            _, product_data = list(exact_products_dict.items())[np.argmin(delta)]
            correct_ref, correct_name = product_data
            self.results_queue.put(('success', 'goszakupki_search', [correct_ref, correct_name]))
        else:
            self.results_queue.put(('fail', 'goszakupki_search', [category, exact_products_dict]))

    def copy_chars(self):
        locator = (By.XPATH,
                   "//button[.//span[contains(normalize-space(.), 'Копировать характеристики')]]"
                   )
        copy_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable(locator)
        )

        actions = ActionChains(self.driver)
        actions.move_to_element(copy_button).pause(1).click().perform()

        copy_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable(locator)
        )
        actions = ActionChains(self.driver)
        actions.move_to_element(copy_button).pause(1).click().perform()

    def match_params(self, choice_params, goszakupki_ref):
        """
        Получение параметров + связка
        :param choice_params:
        :param goszakupki_ref:
        :return:
        """
        if self.check_cancelled():
            self.results_queue.put(('stopped', 'match_params', ''))
            return

        logger.info('Ищу характеристики товара на сайте госзакупки по адресу %s' % goszakupki_ref)

        embedded_dict = {}
        results = []

        for key in choice_params.keys():
            embed = self.get_embedding([key])['embeddings'][0]
            embedded_dict[key] = embed

        self.driver.get(goszakupki_ref)

        time.sleep(3)
        tables = self.driver.find_elements(by=By.XPATH, value='//tr[count(td) = 2 and count(*) = 2]')

        # Перебираем все найденные строки
        for row in tables:
            # Находим все ячейки td в текущей строке
            if self.check_cancelled():
                self.results_queue.put(('stopped', 'match_params', ''))
                return

            current_result = {
                'description': '',
                'default_value': ''
            }

            cells = row.find_elements(by=By.XPATH, value='./td')

            # Проверяем, что нашли ровно две ячейки
            if len(cells) == 2:
                # Извлекаем текст из ячеек
                param_name = cells[0].text
                current_result['name'] = param_name

                if ',' in param_name:
                    param_name = param_name.split(',')[0]

                res, score = self.get_embedding.get_nearest(param_name, embedded_dict)

                category_value = choice_params[res].lower()

                values = [value.lower() for value in cells[1].text.split('\n')]
                current_result['values'] = values
                links = cells[1].find_elements(by=By.XPATH, value='.//span')
                current_result['refs'] = {value: link for value, link in zip(values, links)}

                try:
                    if category_value in values:
                        button = links[values.index(category_value)]
                        logger.debug('%s -> %s \t %s ' % (param_name, res, score))

                        button.click()
                        current_result['default_value'] = category_value
                        current_result['description'] = res

                    elif bool(re.search('[a-z]', values[0])) or (
                            bool(re.search('[а-я]', values[0])) and values[0] not in ['да', 'нет', 'есть']):
                        flag = False
                        for val_i, value in enumerate(values):
                            for key in choice_params:
                                if choice_params[key].lower() == value:
                                    links[val_i].click()
                                    current_result['default_value'] = value
                                    current_result['description'] = res
                                    flag = True
                                    break
                            if flag:
                                break

                    elif re.search(r'\d+', category_value) is not None:
                        category_value = re.search(r'\d+', category_value)[0]
                        category_value = float(category_value)

                        delta = []

                        for key, button in zip(values, links):
                            key = key.strip().split()
                            if key[0] in ['≤', '≥', '<', '>']:
                                sign, number = key
                                number = float(number)

                                if sign == '≤' and category_value <= number:
                                    delta.append(number - category_value)
                                elif sign == '<' and category_value < number:
                                    delta.append(number - category_value)
                                elif sign == '≥' and category_value >= number:
                                    delta.append(category_value - number)
                                elif sign == '>' and category_value > number:
                                    delta.append(category_value - number)
                                else:
                                    delta.append(np.inf)
                        if len(delta) == 0:
                            pass
                        else:
                            logger.debug('%s -> %s, %s' % (param_name, res, score))
                            logger.debug('\t %s -> %s' % (category_value, values[np.argmin(delta)]))

                            links[np.argmin(delta)].click()
                            current_result['default_value'] = values[np.argmin(delta)]
                            current_result['description'] = res
                    else:
                        pass
                except Exception as e:
                    pass
            results.append(current_result)
        self.results_queue.put(('success', 'goszakupki_parsing', results))

    @staticmethod
    def get_effective_color(color, mode, widget):
        if isinstance(color, tuple) or isinstance(color, list):
            selected = color[0] if mode == "light" else color[1]
        else:
            selected = color
        if not selected.startswith('#'):
            r, g, b = widget.winfo_rgb(selected)
            selected = '#%02x%02x%02x' % (r // 256, g // 256, b // 256)
        return selected

    @staticmethod
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def rgb_to_hex(rgb):
        return '#%02x%02x%02x' % rgb

    def interpolate_color(self, color1, color2, t):
        r1, g1, b1 = self.hex_to_rgb(color1)
        r2, g2, b2 = self.hex_to_rgb(color2)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return self.rgb_to_hex((r, g, b))


# if __name__ == '__main__':
#     t = Tools(None)
#     with open('res.pickle', 'rb') as f:
#         res_ = pickle.load(f)
#     t.match_params(res_, 'https://moy-zakupki.ru/ktru/26.20.11.110-00000141/')
