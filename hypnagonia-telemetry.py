import json, os, random, re, json, requests, argparse, logging, threading, time
from flask import Flask
from flask_restful import Resource, reqparse, Api
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from uuid import uuid4
from collections import Counter



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

def regenerate(encounters, encounter, type, amount):
    logging.info(f"Generating: {encounter} - {type}")
    ai_prompts = encounters[encounter]['prompts'][type]
    rindex = random.randint(0, len(ai_prompts) - 1)
    ai_prompt = ai_prompts[rindex]
    fmt = {
        "prompt": ai_prompt,
        "title": encounters[encounter].get('title', encounter),
    }
    title = encounters[encounter].get('title', encounter)
    prompt = f"[ Title: {title} ]\n{ai_prompt}"
    gen_dict = {
        "prompt": prompt, 
        "params": {"max_length":60, "frmttriminc": True, "n":amount}, 
        "username": "hypnagonia", 
        "softprompts": ["surrealism_and_dreams_", ''],
        "models": ["KoboldAI/fairseq-dense-2.7B-Nerys", "KoboldAI/OPT-6B-nerys-v2", "KoboldAI/fairseq-dense-13B-Nerys-v2", "KoboldAI/fairseq-dense-13B-Nerys"]
    }
    try:
        gen_req = requests.post('https://horde.dbzer0.com/generate/sync', json = gen_dict)
        new_stories = gen_req.json()
    except:
        logging.errror(gen_req.json())
        return
    for new_story in new_stories:
        full_story = re.sub(r" \[ [\w ]+ \]([ .,;])", r'\1', ai_prompt) + new_story
        logging.info(full_story)
        evaluating_generations[str(uuid4())] = {
            "generation": full_story,
            "ratings": {},
            "title": encounter,
            "type": type,
        }
    write_to_disk()

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
        args = parser.parse_args()
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

def count_evaluations_by_name_type():
    ordered_dict = {}
    for evaluation in evaluating_generations:
        name = evaluating_generations[evaluation]['title']
        type = evaluating_generations[evaluation]['type']
        if name not in ordered_dict:
            ordered_dict[name] = {}
        if type not in  ordered_dict[name]:
            ordered_dict[name][type] = 0
        ordered_dict[name][type] += 1
    return(ordered_dict)

class GenerateStories(object):
    def __init__(self, interval = 5):
        self.interval = interval
        with open("ai_prompts.json") as file:
            self.encounters = json.load(file)
        # logging.info(count_evaluations_by_name_type())
        thread = threading.Thread(target=self.generate, args=())
        thread.daemon = True
        thread.start()

    def generate(self):
        while True:
            for encounter in self.encounters:
                for type in self.encounters[encounter]['prompts']:
                    amount_of_evals = count_evaluations_by_name_type().get(encounter, {}).get(type,0)
                    if amount_of_evals < 5 and len(self.encounters[encounter]['prompts'][type]):
                        amount = 5 - amount_of_evals
                        # I'll remove this when I start sending sample stories to generate from. Then I'll be able to generate more than 1
                        # But while I'm sending random prompts, I want to be able to get a different prompt every time
                        amount = 1 
                        regenerate(self.encounters, encounter, type, amount)
                        
            time.sleep(self.interval)


# Parse and print the results
if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-i', '--ip', action="store", default='127.0.0.1', help="The listening IP Address")
    arg_parser.add_argument('-p', '--port', action="store", default='8000', help="The listening Port")
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s',level=logging.DEBUG)
    if os.path.isfile(evaluating_generations_filename):
        with open(evaluating_generations_filename) as db:
            evaluating_generations = json.load(db)
        with open(finalized_generations_filename) as db:
            finalized_generations = json.load(db)
    stat_args = arg_parser.parse_args()
    GenerateStories()
    api.add_resource(Generation, "/generation/")
    api.add_resource(EvaluatingGenerations, "/generations/evaluating/")
    api.add_resource(FinalizedGenerations, "/generations/finalized/")
    from waitress import serve
    serve(REST_API, host=stat_args.ip, port=stat_args.port)
    # REST_API.run(debug=True,host=stat_args.ip,port=stat_args.port)