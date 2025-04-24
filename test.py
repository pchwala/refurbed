from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Home"

@app.route("/hello")
def hello():
    return "Hello world"

@app.route("/user/<name>")
def greet(name):
    return f"Hello {name}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)


"""
import functions_framework

@functions_framework.http
def hello_http(request):
    request_json = request.get_json(silent=True)
    request_args = request.args

    if request_json and 'name' in request_json:
        name = request_json['name']
    elif request_args and 'name' in request_args:
        name = request_args['name']
    else:
        name = 'World'
    return 'Hello {}!'.format(name)

"""