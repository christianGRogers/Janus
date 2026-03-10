class Node:
    def __init__(self, id, status="available"):
        self.id = id
        self.status = status
        self.ports = None