import logging
from flask import Flask
import json
import requests
from google.cloud import firestore, secretmanager
from mailjet_rest import Client
from pprint import pformat

db = firestore.Client()

app = Flask(__name__)

client = secretmanager.SecretManagerServiceClient()
path = client.secret_version_path('reservation-gov-checker', 'mailjet-api-key', 'latest')
mailjet_keys = json.loads(client.access_secret_version(path).payload.data)
mailjet = Client(auth=(mailjet_keys['api_key'], mailjet_keys['api_secret']), version='v3.1')

@app.route('/check-availability', methods=['GET'])
def check_availability():
    permit_id = '233261'
    desired_spots = frozenset(['299', '301', '305', '316', '328', '329', '331', '332', '334', '338', '339', '340', '343', '344', '345', '348', '349', '350'])
    spots_needed = 0

    resp = requests.get('https://www.recreation.gov/api/permits/{}/availability/month?start_date=2020-08-01T00:00:00.000Z&commercial_acct=false&is_lottery=false'.format(permit_id),
                            headers={'User-Agent' : 'python'})
    resp.raise_for_status()

    avail = resp.json()['payload']['availability']

    spots = {}
    for (k, v) in avail.items():
        if (k in desired_spots and
                len(v) > 0 and
                'date_availability' in v and
                '2020-08-14T00:00:00Z' in v['date_availability']):
            remaining = v['date_availability']['2020-08-14T00:00:00Z']['remaining']
            if remaining > spots_needed:
                spots[k] = remaining

    resp = requests.get('https://www.recreation.gov/api/permitcontent/{}'.format(permit_id),
                            headers={'User-Agent' : 'python'})
    resp.raise_for_status()

    named_spots = {}
    for id, remaining in spots.items():
        named_spots[resp.json()['payload']['divisions'][id]['name']] = remaining

    doc_ref = db.collection('availability-states').document(permit_id)
    previous = doc_ref.get().to_dict()

    if previous != named_spots:
        logging.info('Differences found: %s', named_spots)

        result = mailjet.send.create(data={
            'Messages': [{
                'From': {
                    'Email': 'reservation.gov.checker@gmail.com', 'Name': 'Reservation.gov Checker'
                    },
                'To': [ { 'Email': 'wbmoss@gmail.com', 'Name': 'Will' } ],
                'Subject': 'New Campsites Available',
                'TextPart': pformat(named_spots)
                }]
            })

        doc_ref.set(named_spots)

        return 'Differences found!<br/><br/><pre>{}</pre>'.format(pformat(named_spots))

    logging.info('No differences found: %s', named_spots)
    return 'No differences found!<br/><br/><pre>{}</pre>'.format(pformat(named_spots))

if __name__ == '__main__':
    # This is used when running locally. Gunicorn is used to run the
    # application on Google App Engine. See entrypoint in app.yaml.
    app.run(host='127.0.0.1', port=8080, debug=True)
