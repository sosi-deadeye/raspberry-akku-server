import database
from twilio.rest import Client
import time


SLEEP_TIME = 2 * 3600


account_sid = "xxx"
auth_token  = "xxx"
sender = '+13203104684'


def send_alert(body, receiver='+4917624045105', sender=sender, whatsapp=False):
    client = Client(account_sid, auth_token)
    if whatsapp:
        receiver = f'whatsapp:{receiver}'
        sender = f'whatsapp:{sender}'
    print(f'From: {sender}')
    print(f'To: {receiver}')
    message = client.messages.create(
        to=receiver,
        from_=sender,
        body=body,
        )
    return message


while True:
    charge = round(database.get_charge_mean(), 2)
    msg = f'Ladung: {charge} Ah'
    try:
        message = send_alert(msg)
    except Exception as e:
        print('Error:', e)
        continue
    print(msg)
    #print(message.sid)
    time.sleep(SLEEP_TIME)
