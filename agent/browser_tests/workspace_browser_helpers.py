"""Data workspace controls that work in desktop panes and mobile steps."""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select


def click(browser, selector):
    element = browser.find_element(By.CSS_SELECTOR, selector)
    step = browser.execute_script("const pane=arguments[0].closest('.data-pane'); return pane?.hidden ? pane.getAttribute('aria-labelledby') : null;", element)
    if step:
        browser.find_element(By.ID, step).click()
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
    element.click()
    return element


def choose(browser, identifier, value):
    element = browser.find_element(By.ID, identifier)
    step = browser.execute_script("const pane=arguments[0].closest('.data-pane'); return pane?.hidden ? pane.getAttribute('aria-labelledby') : null;", element)
    if step:
        browser.find_element(By.ID, step).click()
    browser.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
    Select(element).select_by_value(value)


