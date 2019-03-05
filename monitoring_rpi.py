import time
import hashlib
import commands
import os
import requests

# GitHub API settings
API_URL = 'https://api.github.com'
REPO_URL = API_URL + '/repos/bdeinsalyon/AD-monitoring-client'
LATEST_RELEASE = '/releases/latest'
COMMIT_PATH = '/commits'
TAG_PATH = '/git/refs/tags/'
HEADERS = {'Accept': 'application/vnd.github.cryptographer-preview+json'}

SCRIPT_NAME = os.path.basename(__file__)
SCRIPT_FILE = os.path.abspath(__file__)
UPDATE_FILE = '/tmp/updated.py'


token = commands.getoutput('md5sum /etc/machine-id | awk \'{print $1;}\'').strip()
control_mode = "none"
if control_mode == "lg-serial":
    import serial
elif control_mode == "cec":
    import cec


def getCPUtemperature():
    res = float(commands.getoutput('cat /sys/class/thermal/thermal_zone0/temp'))
    return (res / 1000)


def send(jsonData):
    try:
        # On envoi les donnees recuperees. En retour le recepteur nous renvoi si la tele doit etre eteinte ou allumee a ce moment.
        url = "http://affichage-test.bde-insa-lyon.fr/screen_monitoring_endpoint/"
        jsonData["token"] = token
        print(jsonData)
        r = requests.post(url, data=jsonData)
        return r.text
    except requests.exceptions.RequestException as e:
        print("error request")
        print
        e
        return 3

def update():
    r = requests.get(REPO_URL + COMMIT_PATH, headers=HEADERS)
    json = r.json()
    if 'message' in json:
        print(json)
        return "Json"
    commit = json[0]
    verified = commit.get('commit').get('verification').get('verified')
    sha = commit.get('sha')
    if not verified:
        return "Pas verifie"
    r = requests.get(REPO_URL + COMMIT_PATH + '/' + sha, headers=HEADERS)
    files = r.json().get('files')
    url = None
    for f in files:
        if f.get('filename') == SCRIPT_NAME:
            url = f.get('raw_url')
    if url is None:
        return "Pas d'url"
    r = requests.get(url)

    # If we don't get a successful request, don't update with the returned content.
    if r.status_code not in [200, 301, 302]:
        return "Mauvais status code"

    if r.text.startswith('<html><body><h1>503'):
        return "Erreur 503"

    with open(UPDATE_FILE, 'w') as f:
        f.write(r.text)
    with open(UPDATE_FILE, 'rb') as f1:
        with open(SCRIPT_FILE, 'rb') as f2:
            h1 = hashlib.sha256(f1.read()).hexdigest()
            h2 = hashlib.sha256(f2.read()).hexdigest()

    restart_needed = h1 != h2
    print('restart_needed', restart_needed)
    if restart_needed:
        os.system("sudo mount -o remount,rw /")
        os.remove(SCRIPT_FILE)
        os.system("/bin/cp " + UPDATE_FILE + " " + SCRIPT_FILE)
        print("Reboot dans 10 sec")
        time.sleep(10)
        os.system("/sbin/reboot")
    else:
        print("Restart non necessaire")
        os.remove(UPDATE_FILE)



print(update())
if control_mode == "cec":
    # On initialise le CEC
    cec.init()
    tv = cec.Device(0)
    cec.set_active_source(1)

while 1:  # Boucle qui pool toutes les 1 min, on utilise pas cron car la connexion au CEC est longue et pas faites pour rester que quelques secondes. Elle est faite pour rester connectee.
    print
    "Start Pooling"
    # Construction du JSON de donnees monitoring
    jsonData = {}
    jsonData["temperature"] = round(getCPUtemperature(), 1)
    #jsonData["heure"] = round(time.time(), 0)
    load = os.getloadavg()
    jsonData["load"] = str(load[0]) + " " + str(load[1]) + " " + str(load[2])
    jsonData["tv_screen_on"] = 0
    jsonData["ip"] = commands.getoutput('hostname -I').strip()
    jsonData["hostname"] = commands.getoutput('hostname').strip()
    # jsonData["fs"] = commands.getoutput('/kiosk/check_fs.sh')
    jsonData["fs_ro"] = 1
    if control_mode == "lg-serial":
        ser = serial.Serial('/dev/ttyUSB0', timeout=4)
        time.sleep(1)
        ser.write(b'ka 00 ff\n')
        etat_tv_serial = ser.readline()
        print
        etat_tv_serial
        if (etat_tv_serial == "a 01 OK01x"):
            jsonData["tv_screen_on"] = 1
            tv_is_on = 1
        else:
            jsonData["tv_screen_on"] = 0
            tv_is_on = 0
    elif control_mode == "cec":
        tv_is_on = tv.is_on()
        tv_rasp_active = cec.is_active_source(1)
        if tv_is_on and tv_rasp_active:
            jsonData["tv_screen_on"] = 1
        else:
            jsonData["tv_screen_on"] = 0

    envoi = send(jsonData)
    # On verifie que ce que demande le recepteur est egal a la realite, sinon on execute les commandes pour corriger
    if control_mode == "lg-serial":
        if int(envoi) == 1 and (not tv_is_on):
            ser.write(b'ka 00 01\n')
            ser.write(b'xb 00 90\n')
            print
            "J'allume"
        elif int(envoi) == 0 and tv_is_on:
            print
            "J eteinds"
            ser.write(b'ka 00 00\n')
        ser.close()
    elif control_mode == "cec":
        if int(envoi) == 1 and (not tv_rasp_active or not tv_is_on):
            print
            "J'allume"
            tv.power_on()
            cec.set_active_source(1)
        elif int(envoi) == 0 and tv_is_on:
            print
            "J eteinds"
            tv.standby()
    print
    "End Pooling"
    # On dort 2 min en laissant la connexion CEC active
    time.sleep(120)