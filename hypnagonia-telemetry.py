from flask import Flask
from flask_restful import Resource, reqparse, Api
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from uuid import uuid4
import json, os
import argparse

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-i', '--ip', action="store", default='127.0.0.1', help="The listening IP Address")
arg_parser.add_argument('-p', '--port', action="store", default='8000', help="The listening Port")

generations_filename = "generations.json"
stats_filename = "stats.json"

REST_API = Flask(__name__)
# Very basic DOS prevention
limiter = Limiter(
	REST_API,
	key_func=get_remote_address,
	default_limits=["90 per minute"]
)
api = Api(REST_API)

generations = {}

def write_to_disk():
	with open(generations_filename, 'w') as db:
		json.dump(generations,db)

@REST_API.after_request
def after_request(response):
	response.headers["Access-Control-Allow-Origin"] = "*"
	response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS, PUT, DELETE"
	response.headers["Access-Control-Allow-Headers"] = "Accept, Content-Type, Content-Length, Accept-Encoding, X-CSRF-Token, Authorization"
	return response

class Generation(Resource):
    # decorators = [limiter.limit("4/minute")]
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument("uuid", type=str, required=True, help="UUID of the generation")
        parser.add_argument("generation", type=str, required=True, help="Content of the generattion")
        parser.add_argument("title", type=str, required=True, help="The name of the thing for which we're generating")
        parser.add_argument("type", type=str, required=True, help="The type of generation it is. This is used for finding previous such generations")
        parser.add_argument("classification", type=int, required=True, help="An enum for whether the player liked this story and the classification of such")
        parser.add_argument("client_id", type=str, required=True, help="The unique ID for this version of Hypnagonia client")
        args = parser.parse_args()
        gtitle = args["title"]
        gtype = args["type"]
        guuid = args["uuid"]
        generation = args["generation"]
        gclid = args["client_id"]
        classification = args["classification"]
        if gtitle not in generations:
            generations[gtitle] = {}
        if gtype not in generations[gtitle]:
            generations[gtitle][gtype] = {}
        if guuid not in generations[gtitle][gtype]:
            generations[gtitle][gtype][guuid] = {
                "generation": generation,
                "ratings": {}
            }
        if gclid in generations[gtitle][gtype][guuid]["ratings"] and generations[gtitle][gtype][guuid]["ratings"][gclid] == classification:
            return(204)
        else:
            generations[gtitle][gtype][guuid]["ratings"][gclid] = classification
        write_to_disk()
        return(204)

    def options(self):
        return("OK", 200)


# Parse and print the results
if __name__ == "__main__":
    if os.path.isfile(generations_filename):
        with open(generations_filename) as db:
            games = json.load(db)
    stat_args = arg_parser.parse_args()
    api.add_resource(Generation, "/generation/")
    from waitress import serve
    serve(REST_API, host=stat_args.ip, port=stat_args.port)
    # app.run(debug=True,host=stat_args.ip,port=stat_args.port)