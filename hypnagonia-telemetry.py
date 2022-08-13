from flask import Flask
from flask_restful import Resource, reqparse, Api
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from uuid import uuid4
import json, os
import argparse
from collections import Counter
import requests

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-i', '--ip', action="store", default='127.0.0.1', help="The listening IP Address")
arg_parser.add_argument('-p', '--port', action="store", default='8000', help="The listening Port")

evaluating_generations_filename = "evaluating_generations.json"
finalized_generations_filename = "finalized_generations.json"
stats_filename = "stats.json"

REST_API = Flask(__name__)
# Very basic DOS prevention
limiter = Limiter(
	REST_API,
	key_func=get_remote_address,
	default_limits=["90 per minute"]
)
api = Api(REST_API)

evaluating_generations = {}
finalized_generations = {}

def write_to_disk():
	with open(evaluating_generations_filename, 'w') as db:
		json.dump(evaluating_generations,db)
	with open(finalized_generations_filename, 'w') as db:
		json.dump(finalized_generations,db)


def get_rating(guuid):
    counts = Counter(evaluating_generations[guuid]["ratings"].values())
    max_ratings = [key for key, value in counts.items() if value == max(counts.values())]
    return(max_ratings)

@REST_API.after_request
def after_request(response):
	response.headers["Access-Control-Allow-Origin"] = "*"
	response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS, PUT, DELETE"
	response.headers["Access-Control-Allow-Headers"] = "Accept, Content-Type, Content-Length, Accept-Encoding, X-CSRF-Token, Authorization"
	return response

def instance_verified(kai_instance):
    valid_models = [
        "KoboldAI/fairseq-dense-2.7B-Nerys",
        "KoboldAI/fairseq-dense-13B-Nerys",
    ]
    try:
        model = requests.get(kai_instance + '/api/latest/model')
    except:
        print("Validation failed to get URL: " + kai_instance + '/api/latest/model')
        return(False)
    if type(model.json()) is not dict:
        print("Validation failed to parse softprompt API: " + model.text)
        return(False)
    if model.json()["result"] not in valid_models:
        print("Validation failed because: " + model.json()["result"] + " is not a valid model")
        return(False)

    try:
        softprompt = requests.get(kai_instance + "/api/latest/config/soft_prompt")
    except:
        print("Validation failed to get URL: " + kai_instance + "/api/latest/config/soft_prompt")
        return(False)
    if type(softprompt.json()) is not dict:
        print("Validation failed to parse softprompt API: " + softprompt.text)
        return(False)
    valid_softprompts = [
        "surrealism_and_dreams_2.7B.zip",
        "surrealism_and_dreams_13B.zip",
    ]
    if softprompt.json()["value"] not in valid_softprompts:
        print("Validation failed because: " + softprompt.json()["value"] + " is not a valid softprompt")
        return(False)
    return(True)

class Generation(Resource):
    decorators = [limiter.limit("10/minute")]
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("uuid", type=str, required=True, help="UUID of the generation")
        parser.add_argument("generation", type=str, required=True, help="Content of the generattion")
        parser.add_argument("title", type=str, required=True, help="The name of the thing for which we're generating")
        parser.add_argument("type", type=str, required=True, help="The type of generation it is. This is used for finding previous such generations")
        parser.add_argument("classification", type=int, required=True, help="An enum for whether the player liked this story and the classification of such")
        parser.add_argument("client_id", type=str, required=True, help="The unique ID for this version of Hypnagonia client")
        parser.add_argument("kai_instance", type=str, required=True, help="The instance where Kobold AI is running on. We use it for verification.")
        args = parser.parse_args()
        if not instance_verified(args["kai_instance"]):
            return
        gtitle = args["title"]
        gtype = args["type"]
        guuid = args["uuid"]
        generation = args["generation"]
        gclid = args["client_id"]
        classification = args["classification"]
        if guuid in finalized_generations:
            if gclid in finalized_generations[guuid]["ratings"] and finalized_generations[guuid]["ratings"][gclid] == classification:
                return(204)
            else:
                finalized_generations[guuid]["ratings"][gclid] = classification
        else:
            if guuid not in evaluating_generations:
                evaluating_generations[guuid] = {
                    "generation": generation,
                    "submitter": gclid,
                    "ratings": {},
                    "title": gtitle,
                    "type": gtype,
                }
            if gclid in evaluating_generations[guuid]["ratings"] and evaluating_generations[guuid]["ratings"][gclid] == classification:
                return(204)
            else:
                evaluating_generations[guuid]["ratings"][gclid] = classification
                # We need 5 different players to evaluate one generation to consider it finalized

                if len(evaluating_generations[guuid]["ratings"]) >= 5:
                    highest_ratings = get_rating(guuid)
                    evaluated_gen = evaluating_generations.pop(guuid)
                    # 0 means most people disliked this generation, so we forget the generation if 0 is one of the highest ratings
                    if 0 not in highest_ratings:
                        finalized_generations[guuid] = evaluated_gen
                        print("Finalizing generation: " + generation)
                    else:
                        print("Rejecting generation: " + generation)
        write_to_disk()
        return(204)

class EvaluatingGenerations(Resource):
    decorators = [limiter.limit("2/minute")]
    def get(self):
        return(evaluating_generations, 200)

    def options(self):
        return("OK", 200)

class FinalizedGenerations(Resource):
    decorators = [limiter.limit("2/minute")]
    def get(self):
        return(finalized_generations, 200)

    def options(self):
        return("OK", 200)


# Parse and print the results
if __name__ == "__main__":
    if os.path.isfile(evaluating_generations_filename):
        with open(evaluating_generations_filename) as db:
            evaluating_generations = json.load(db)
        with open(finalized_generations_filename) as db:
            finalized_generations = json.load(db)
    stat_args = arg_parser.parse_args()
    api.add_resource(Generation, "/generation/")
    api.add_resource(EvaluatingGenerations, "/generations/evaluating/")
    api.add_resource(FinalizedGenerations, "/generations/finalized/")
    from waitress import serve
    serve(REST_API, host=stat_args.ip, port=stat_args.port)
    # REST_API.run(debug=True,host=stat_args.ip,port=stat_args.port)