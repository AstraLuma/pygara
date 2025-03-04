from pygara import TangaraDB

db = TangaraDB("/media/astraluma/9EE9-1BAD/.tangara-db")
for track in db.iter_tracks():
    print(track)
    for key, value in track.metadata().items():
        print(f"  {key.name}: {value}")
