import datetime
import pickle
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pandas as pd

abs_path = '/home/pi/Desktop/Projects/wsbtickerbot/'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
# The file token.pickle stores the user's access and refresh tokens, and is
# created automatically when the authorization flow completes for the first
# time.
# token_path = '/path/to/token.pickle'
token_path = abs_path+'token.pickle'
# credentials_path = '/path/to/credentials.json'
credentials_path = abs_path+'credentials.json'

def create_service(mode):
	creds = None

	if os.path.exists(token_path):
		with open(token_path, 'rb') as token:
			creds = pickle.load(token)
	# If there are no (valid) credentials available, let the user log in.
	if not creds or not creds.valid:
		if creds and creds.expired and creds.refresh_token:
			creds.refresh(Request())
		else:
			flow = InstalledAppFlow.from_client_secrets_file(
				credentials_path, SCOPES)
			creds = flow.run_local_server()
		# Save the credentials for the next run
		with open(token_path, 'wb') as token:
			pickle.dump(creds, token)

	return build('sheets', 'v4', credentials=creds)

def get_google_sheet(spreadsheet_id, range_name):
	service = create_service('sheets')

	# Call the Sheets API
	gsheet = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
	return gsheet

def gsheet2df(gsheet):
	""" Converts Google sheet data to a Pandas DataFrame.
	Note: This script assumes that your data contains a header file on the first row!
	Also note that the Google API returns 'none' from empty cells - in order for the code
	below to work, you'll need to make sure your sheet doesn't contain empty cells,
	or update the code to account for such instances.
	"""
	header = gsheet.get('values', [])[0]   # Assumes first line is header!
	values = gsheet.get('values', [])[1:]  # Everything else is data.
	if not values:
		print('No data found.')
	else:
		all_data = []
		for col_id, col_name in enumerate(header):
			column_data = []
			for row in values:
				column_data.append(row[col_id])
			ds = pd.Series(data=column_data, name=col_name)
			all_data.append(ds)
		df = pd.concat(all_data, axis=1)
		return df

def get_stonks_email_df():
	SPREADSHEET_ID = '1b2LjHDpHTxH3brtXpqy40KvbP_PFj_3BelwatZCnF1w'

	sheet = get_google_sheet(SPREADSHEET_ID, 'Emails')
	return gsheet2df(sheet)
	