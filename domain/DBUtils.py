import btree

# First, we need to open a stream which holds a database
# This is usually a file, but can be in-memory database
# using uio.BytesIO, a raw flash partition, etc.
# Oftentimes, you want to create a database file if it doesn't
# exist and open if it exists. Idiom below takes care of this.
# DO NOT open database with "a+b" access mode.
db=None
dbFile=None

def openDB():
    global db
    global dbFile
    if dbFile == None:
        try:
            dbFile = open("mydb", "r+b")
        except OSError:
            dbFile = open("mydb", "w+b")

    if db == None:
        # Now open a database itself
        db = btree.open(dbFile)

def closeDB():
    global db
    global dbFile
    if db != None:
        db.close()
        db = None

    if dbFile != None:
        dbFile.close()
        dbFile = None


# The keys you add will be sorted internally in the database

def testDB(prefix,count):
    global db
    print("+++start insert. prefix:{},count:{}".format(prefix,count))
    openDB()

    for i in range(count):
        db[str(i)] = prefix+":"+str(i)

    closeDB()
    print("insert finish.")

    print("---start query.")
    openDB()
    for key in db:
        print("key:{},value:{}".format(key,db[key]))
    closeDB()
    print("test db finish.")

def save(kv):
    if None == kv or len(kv) == 0:
        return
    
    global db
    openDB()
    for k,v in kv.items():
        db[k] = v
    db.flush()
    closeDB()

def get(k):
    global db
    openDB()
    res = None
    if k in db:
        res = db[k]  
    closeDB()
    return res

def multiGet(keys):
    global db
    openDB()
    res = {}
    for k in keys:
        if k in db:
            res[k] = db[k]
        else:
            res[k] = None  
    closeDB()
    return res

def _to_str(val):
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val

def getAll(verbose=False):
    global db
    openDB()
    res = {}
    for key in db:
        k = _to_str(key)
        v = _to_str(db[key])
        res[k] = v
        if verbose:
            print("key:{},value:{}".format(k, v))
    closeDB()
    return res

def set(k, v):
    global db
    openDB()
    db[k] = v
    db.flush()
    closeDB()

def delete(k):
    global db
    openDB()
    if k in db:
        del db[k]
        db.flush()
    closeDB()

def count():
    global db
    openDB()
    n = sum(1 for _ in db)
    closeDB()
    return n

def contains(k):
    global db
    openDB()
    found = k in db
    closeDB()
    return found




# # Assume that any changes are cached in memory unless
# # explicitly flushed (or database closed). Flush database
# # at the end of each "transaction".
# db.flush()

# # Prints b'two'
# print(db[b"2"])

# # Iterate over sorted keys in the database, starting from b"2"
# # until the end of the database, returning only values.
# # Mind that arguments passed to values() method are *key* values.
# # Prints:
# #   b'two'
# #   b'three'
# for word in db.values(b"2"):
#     print(word)

# del db[b"2"]

# # No longer true, prints False
# print(b"2" in db)

# # Prints:
# #  b"1"
# #  b"3"
# for key in db:
#     print(key)

# db.close()

# # Don't forget to close the underlying stream!
# dbFile.close()