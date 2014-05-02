from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
import random
import time

from ..SocketInterface import clientsocket
from utils.lso import get_flash_cookies
from utils.firefox_profile import get_localStorage, get_cookies, sleep_until_sqlite_checkpoint

# Library for core WebDriver-based browser commands

# goes to <url> using the given <webdriver> instance
# <proxy_queue> is queue for sending the proxy the current first party site
def get_website(url, webdriver, proxy_queue):
    main_handle = webdriver.current_window_handle
    # sends top-level domain to proxy
    # then, waits for it to finish marking traffic in queue before moving to new site
    if proxy_queue is not None:
        proxy_queue.put(url)
        while not proxy_queue.empty():
            time.sleep(0.001)
    
    # Execute a get through selenium
    try:
        webdriver.get(url)
    except TimeoutException:
        pass
    
    # Close modal dialog if exists
    try:
        WebDriverWait(webdriver, .5).until(EC.alert_is_present())
        alert = webdriver.switch_to_alert()
        alert.dismiss()
        time.sleep(1)
    except TimeoutException:
        pass

    # Close other windows (popups or "tabs")
    windows = webdriver.window_handles
    if len(windows) > 1:
        for window in windows:
            if window != main_handle:
                webdriver.switch_to_window(window)
                webdriver.close()
        webdriver.switch_to_window(main_handle)

    # Sleep for a bit
    time.sleep(5)

    # Create a new tab and kill this one to stop traffic
    # NOTE: This code is firefox specific
    switch_to_new_tab = ActionChains(webdriver)
    switch_to_new_tab.key_down(Keys.CONTROL + 't') # open new tab
    switch_to_new_tab.key_up(Keys.CONTROL + 't')
    switch_to_new_tab.key_down(Keys.CONTROL + Keys.PAGE_UP) # switch to prev tab
    switch_to_new_tab.key_up(Keys.CONTROL + Keys.PAGE_UP)
    switch_to_new_tab.key_down(Keys.CONTROL + 'w') # close tab
    switch_to_new_tab.key_up(Keys.CONTROL + 'w')
    switch_to_new_tab.perform()
    time.sleep(5)
    
    # Add bot detection mitigation techniques
    # TODO: make this an option in the future?
    # move the mouse to random positions a number of times
    #for i in range(0,10):
    #    x = random.randrange(0,500)
    #    y = random.randrange(0,500)
    #    action = ActionChains(webdriver)
    #    action.move_by_offset(x,y)
    #    action.perform

    # scroll to bottom of page
    #webdriver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    # random wait time
    #time.sleep(random.randrange(1,7))

def dump_storage_vectors(top_url, start_time, profile_dir, db_socket_address):
    # Set up a connection to DataAggregator
    sock = clientsocket()
    sock.connect(*db_socket_address)

    # Wait for SQLite Checkpointing - never happens when browser open
    # sleep_until_sqlite_checkpoint(profile_dir)

    # Flash cookies
    flash_cookies = get_flash_cookies(start_time)
    for cookie in flash_cookies:
        query = ("INSERT INTO flash_cookies (page_url, domain, filename, local_path, \
                  key, content) VALUES (?,?,?,?,?,?)", 
                  (top_url, cookie.domain, cookie.filename, cookie.local_path, 
                  cookie.key, cookie.content))
        sock.send(query)

    # Cookies
    rows = get_cookies(profile_dir, start_time)
    if rows is not None:
        for row in rows:
            query = ("INSERT INTO profile_cookies (page_url, domain, name, value, \
                      host, path, expiry, accessed, creationTime, isSecure, isHttpOnly) \
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)",(top_url,) + row)
            sock.send(query)
    
    # localStorage - TODO support modified time
    '''
    rows = get_localStorage(profile_dir, start_time)
    if rows is not None:
        for row in rows:
            query = ("INSERT INTO localStorage (page_url, scope, KEY, value) \
                      VALUES (?,?,?,?)",(top_url,) + row)
            sock.send(query)
    '''

    # Close connection to db
    sock.close()
