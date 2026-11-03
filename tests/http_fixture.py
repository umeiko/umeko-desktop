"""Socket observations shared by the local generation HTTP fixtures."""


def peer_disconnected(connection):
    try:
        return not connection.recv(1)
    except ConnectionResetError:
        # An abortive TCP close is also a disconnect, not an open connection.
        # Let timeouts and unrelated socket errors fail the fixture normally.
        return True
