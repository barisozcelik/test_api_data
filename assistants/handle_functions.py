from jsonschema import validate
from jsonschema.exceptions import ValidationError
import requests
from typing import Dict, Any, List, Optional
import uuid
import json
import os

domain = ""
api_key = ''


def retrieve_function_schema(function_definitions, function_name):
  for function_definition in function_definitions:
    if 'function' not in function_definition:
       continue
    if function_definition['function']['name'] == function_name:
      return function_definition['function']['parameters']

def validate_args(args, schema):
    try:
        validate(instance=args, schema=schema)
    except ValidationError as e:
        # You can handle the validation error as you see fit
        error_message = json.dumps({"validation_error": e.message,"validation_schema": schema})
        raise ValueError(error_message)

def get_frame():

  url = f"https://{domain}/persistence/v3/jsonld/frame"

  payload = {}
  headers = {
    'x-api-key': api_key
  }

  response = requests.request("GET", url, headers=headers, data=payload)

  return response.json()

frame = get_frame()


def get_containers(frame):
    containers = []
    context = frame.get("@context")
    for item, value in context.items():
        if type(value) == dict:
            if value.get("@container") == "@set":
                containers.append(item)
    return containers

def find_container(_type, frame):
    containers = get_containers(frame)
    for container in containers:
        container_type = frame[container].get("@type")[0]
        if container_type == _type:
            return container
    return None

def flatten_data(data, frame):
    flattened = {container: [] for container in get_containers(frame)}
    id_map = {}

    def process_item(item, container):
        if '@id' not in item:
            item['@id'] = str(uuid.uuid4())
        id_map[item['@id']] = str(uuid.uuid4())
        flattened[container].append(item)
        return item['@id']

    def process_container_object(class_obj, container_name):
        for key, value in list(class_obj.items()):
            if type(value) == list:
                id_list = []
                for item in value:
                    if type(item) == dict and '@type' in item:
                        _type = item['@type']
                        container = find_container(_type, frame)
                        if container:
                            id_list.append(process_item(item, container))
                if id_list:
                  class_obj[key] = id_list
            elif type(value) == dict and '@type' in value:
                _type = value['@type']
                container = find_container(_type, frame)
                if container:
                    class_obj[key] = process_item(value, container)

        # Add the top-level object to the flattened structure
        if container_name in flattened:
            if '@id' not in class_obj:
                class_obj['@id'] = str(uuid.uuid4())
            flattened[container_name].append(class_obj)
            return class_obj['@id']

    for container_name, containers in data.items():
        for class_obj in containers:
            process_container_object(class_obj, container_name)

    results = {}
    for container, container_data in flattened.items():
        if container_data:
            results[container] = container_data
    return results



def create_collection(data: Dict[str, List[Dict[str, Any]]], transaction_id: str):
  url = f"https://{domain}/persistence/transactions/{transaction_id}/collections"

  headers = {
    'x-api-key': api_key
  }

  response = requests.request("POST", url, headers=headers, json={"data": data,"metadata": {"version": 3,"validation": True}})

  return response.text.encode('utf8')

def create_transaction_call():
  url = f"https://{domain}/persistence/transactions"

  payload = json.dumps({
    "label": "loan-officer-loan-application-gpt"
  })
  headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'x-api-key': api_key
  }

  response = requests.request("POST", url, headers=headers, data=payload)

  return response.text.encode('utf8')



def handle_functions(function_name, args):
  assistant_data_folder = os.path.join(os.path.dirname(__file__), "./data/loan_officer_gpt/assistant.json")

  with open(assistant_data_folder, "r") as file:
    assistant_data = json.load(file)

  function_definitions = assistant_data['tools']
  function_schema = retrieve_function_schema(function_definitions, function_name)
  if function_schema is None:
    raise Exception(f'Function {function_name} not found')
  validate_args(args, function_schema)

  if function_name == 'createTransaction':
     return create_transaction_call()
  else:

    # Refactor this later. 3 levels of flattening is not hardcoded.
    flattened = flatten_data(args['data'], frame)
    flattened2 = flatten_data(flattened, frame)
    flattened3 = flatten_data(flattened2, frame)

    return create_collection(flattened3, args['transaction_id'])




# Create Transaction


def create_transaction(args):
  print(handle_functions('createTransaction',args))

def save_personal_information(args):
  print(handle_functions('recordPersonalInformation',args))
def save_current_residence_information(args):
  print(handle_functions('save_current_residence_information',args))

def save_previous_residence_information(args):
  print(handle_functions('save_previous_residence_information',args))
def save_contact_information(args):
  print(handle_functions('save_contact_information',args))
def save_current_employment(args):
  print(handle_functions('save_current_employment',args))
def save_additional_income(args):
  print(handle_functions('save_additional_income',args))
def save_liabilities(args):
  print(handle_functions('save_liabilities',args))
def save_asset_information(args):
  print(handle_functions('save_asset_information',args))
def save_liabilities_information(args):
  print(handle_functions('save_liabilities_information',args))
def save_expenses(args):
  print(handle_functions('save_expenses',args))
def save_real_estate_information(args):
  print(handle_functions('save_real_estate_information',args))

# create_transaction({"label":"loan-officer-loan-application-gpt"})
# save_personal_information({"data":{"people":[{"@type":"person","full_name":"John Doe","birth_year":"1980","birth_month":"07","birth_day":"15","marital_status_type":"Married","ssn":"123-45-6789","us_citizenship_status":"USCitizen","has_alias":[{"@type":"person","full_name":"Johnny"},{"@type":"person","full_name":"JD"}],"has_dependent":[{"@type":"person","age":8},{"@type":"person","age":10}]}]},"transaction_id":"01HHSVMCNM8YSQ6RYKK8NB3P2A"})
# save_current_residence_information({"data":{"ownerships":[{"@type":"ownership","owned_by":"01HHSW6XRR07V5EDEZ2TV3RJEF","owned_property":{"@type":"property","has_address":{"@type":"address","address_line_1":"123 Main St","unit_identifier":"Unit 101","city_name":"Anytown","state_code":"AL","postal_code":"12345","country_name":"USA"},"property_estimated_value_amount":0,"property_current_usage_type":"Investment","owned_property_maintenance_expense_amount":0,"owned_property_disposition_status_type":"Retain"}}]},"transaction_id":"01HHSVMCNM8YSQ6RYKK8NB3P2A"})
save_contact_information({"data":{"contact_points":[{"@type":"contact_point","person":"01HHSW6XRR07V5EDEZ2TV3RJEF","telephone":"+11234567890","contact_type":"Primary"},{"@type":"contact_point","person":"01HHSW6XRR07V5EDEZ2TV3RJEF","telephone":"+12345678901","contact_type":"Home"},{"@type":"contact_point","person":"01HHSW6XRR07V5EDEZ2TV3RJEF","telephone":"+13456789012","contact_type":"Work"}],"emails":[{"@type":"email","person":"01HHSW6XRR07V5EDEZ2TV3RJEF","email_address":"johndoe@sample.com"}]},"transaction_id":"01HHSVMCNM8YSQ6RYKK8NB3P2A"})

#save_current_employment({"data":{"employments":[{"@type":"employment","associated_income":[{"@type":"income","income_recipient":"01HHS86THY78VVCCRQ9JRYVB1P","income_amount":7000,"income_type":"Base"},{"@type":"income","income_recipient":"01HHS86THY78VVCCRQ9JRYVB1P","income_amount":1000,"income_type":"Bonuses"}],"employment_start_date":"2020-05-03","employment_status_type":"Current","employment_time_in_line_of_work_years_count":8,"has_employee":"01HHS86THY78VVCCRQ9JRYVB1P","has_employer":{"@type":"company","has_address":{"@type":"address","address_line_1":"456 Technology Drive","city_name":"Silicon Valley","state_code":"CA","postal_code":"94025","country_name":"US"},"has_communication_method":{"@type":"communication","phone_number":"(555) 678-1234"},"name":"Orion Tech Solutions"},"position_title":"Lead Software Developer","self_employment_indicator":False,"special_borrower_employer_relationship_indicator":False}]},"transaction_id":"01HHS82KKCXGCKKHAQKE6QDAGH"})
#save_additional_income({"data":{"incomes":[{"@type":"income","income_recipient":"01HHS86THY78VVCCRQ9JRYVB1P","income_amount":2500,"income_type":"NetRentalIncome"}]},"transaction_id":"01HHS82KKCXGCKKHAQKE6QDAGH"})
#save_liabilities({"data":{"liabilities":[{"@type":"liability","liability_type":"CreditCard","monthly_payment":200,"outstanding_balance":5000,"liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P"},{"@type":"liability","liability_type":"AutoLoan","monthly_payment":350,"outstanding_balance":15000,"liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P"},{"@type":"liability","liability_type":"StudentLoan","monthly_payment":450,"outstanding_balance":22000,"liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P"}]},"transaction_id":"01HHS82KKCXGCKKHAQKE6QDAGH"})
#save_liability_information({"data":{"liabilities":[{"@type":"liability","liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P","liability_type":"CreditCard","monthly_payment_amount":200,"unpaid_balance_amount":5000,"liability_account_identifier":"1234-5678-9012"},{"@type":"liability","liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P","liability_type":"AutoLoan","monthly_payment_amount":350,"unpaid_balance_amount":15000,"liability_account_identifier":"9876-5432-1011"},{"@type":"liability","liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P","liability_type":"StudentLoan","monthly_payment_amount":450,"unpaid_balance_amount":22000,"liability_account_identifier":"1122-3344-5566"}]},"transaction_id":"01HHS82KKCXGCKKHAQKE6QDAGH"})
#save_liabilities({"data":{"liabilities":[{"liability_type":"CreditCard","monthly_payment":200,"outstanding_balance":5000,"liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P"},{"liability_type":"AutoLoan","monthly_payment":350,"outstanding_balance":15000,"liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P"},{"liability_type":"StudentLoan","monthly_payment":450,"outstanding_balance":22000,"liability_holder":"01HHS86THY78VVCCRQ9JRYVB1P"}]},"transaction_id":"01HHS82KKCXGCKKHAQKE6QDAGH"})
#save_real_estate_information({"data":{"ownerships":[{"@type":"ownership","owned_by":"01HHSAD8XNTE0S3PMR4475JMAZ","owned_property":{"@id":"owned_property_1","@type":"property","has_address":{"@type":"address","address_line_1":"123 Main St","city_name":"Anytown","state_code":"CA","postal_code":"90210"},"property_estimated_value_amount":350000,"property_current_usage_type":"PrimaryResidence","owned_property_disposition_status_type":"Retain","owned_property_maintenance_expense_amount":0,"rental_estimated_net_monthly_rent_amount":0}},{"@type":"ownership","owned_by":"01HHSAD8XNTE0S3PMR4475JMAZ","owned_property":{"@id":"owned_property_2","@type":"property","has_address":{"@type":"address","address_line_1":"456 Elm St","city_name":"Newtown","state_code":"CA","postal_code":"90211"},"property_estimated_value_amount":400000,"property_current_usage_type":"Investment","owned_property_disposition_status_type":"PendingSale","owned_property_maintenance_expense_amount":0,"rental_estimated_net_monthly_rent_amount":2500}}]},"transaction_id":"01HHSA4KY4Q97T537RFH0R78K6"})
