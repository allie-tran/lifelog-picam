from mongodb_odm import connect

def init_db():
    connect("mongodb://localhost:27017/picam")
