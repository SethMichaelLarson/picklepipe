import os
import struct
import marshal
import unittest
import picklepipe


class TestMarshalPipe(unittest.TestCase):
    def make_pipe_pair(self):
        rd, wr = picklepipe.make_pipe_pair(picklepipe.MarshalPipe)
        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

    def make_socketpair(self):
        from picklepipe.socketpair import socketpair
        return socketpair()

    def patch_default_selector(self):
        from picklepipe import pipe
        old_default = pipe.selectors2.DefaultSelector
        self.addCleanup(setattr, pipe.selectors2, 'DefaultSelector', old_default)
        pipe.selectors2.DefaultSelector = pipe.selectors2.SelectSelector

    def test_send_single_object(self):
        rd, wr = self.make_pipe_pair()
        wr.send_object('abc')
        obj = rd.recv_object(timeout=1.0)
        self.assertEqual(obj, 'abc')

    def test_many_objects(self):
        rd, wr = self.make_pipe_pair()
        for i in range(100):
            wr.send_object(i)
        for i in range(100):
            obj = rd.recv_object(timeout=1.0)
            self.assertEqual(obj, i)

    def test_timeout(self):
        rd, wr = self.make_pipe_pair()
        self.assertRaises(picklepipe.PipeTimeout, rd.recv_object, timeout=0.3)

    def test_only_sent_object_length(self):
        rd, wr = self.make_pipe_pair()
        rd._buffer = b'\x00\x00\x00\x01'
        self.assertRaises(picklepipe.PipeTimeout, rd.recv_object, timeout=0.3)

    def test_only_sent_part_of_object_length(self):
        rd, wr = self.make_pipe_pair()
        rd._buffer = b'\x00\x00\x00'
        self.assertRaises(picklepipe.PipeTimeout, rd.recv_object, timeout=0.3)

    def test_only_sent_part_of_object(self):
        rd, wr = self.make_pipe_pair()
        rd._buffer = struct.pack('>I', 4) + b'\x00\x00\x00'
        self.assertRaises(picklepipe.PipeTimeout, rd.recv_object, timeout=0.3)

    def test_default_version(self):
        rd, wr = self.make_pipe_pair()
        self.assertEqual(rd.version, marshal.version)
        self.assertEqual(wr.version, marshal.version)

    def test_same_version(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=2)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        self.assertEqual(wr.version, 2)
        self.assertEqual(rd.version, 2)

    def test_different_version(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=1)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        self.assertEqual(wr.version, 1)
        self.assertEqual(rd.version, 1)

    def test_fileno(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=1)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        self.assertEqual(rd.fileno(), r.fileno())
        self.assertEqual(wr.fileno(), w.fileno())

    def test_close_pipe(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=1)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        self.assertIs(wr.closed, False)
        self.assertIs(rd.closed, False)

        wr.close()
        self.assertIs(wr.closed, True)

        rd.close()
        self.assertIs(rd.closed, True)

    def test_recv_unpicklable_object(self):
        rd, wr = self.make_pipe_pair()
        rd._recv_version()
        rd._buffer = struct.pack('>I', 128) + os.urandom(128)
        self.assertRaises(picklepipe.PipeUnserializingError, rd.recv_object, timeout=0.3)
        self.assertIs(rd.closed, False)

    def test_send_object_to_closed_reading_socket_before_proto(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=1)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        r.close()
        self.assertRaises(picklepipe.PipeClosed, wr.send_object, 'abc')

    def test_send_object_to_closed_reading_socket_after_proto(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=1)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        rd._recv_version()
        wr._recv_version()
        r.close()
        self.assertRaises(picklepipe.PipeClosed, wr.send_object, 'abc')

    def test_send_object_to_closed_writing_socket(self):
        r, w = self.make_socketpair()
        rd = picklepipe.MarshalPipe(r, version=1)
        self.addCleanup(rd.close)
        wr = picklepipe.MarshalPipe(w, version=2)
        self.addCleanup(wr.close)

        rd._recv_version()
        wr._recv_version()
        w.close()
        self.assertRaises(picklepipe.PipeClosed, wr.send_object, 'abc')

    def test_erroring_socket(self):
        class FakeSocket(object):
            def __init__(self):
                self._sent = False

            def recv(self):
                return b'\x01'

            def setblocking(self, *_):
                pass

            def fileno(self):
                return 123

            def sendall(self, *_):
                if self._sent:
                    raise OSError()
                self._sent = True

        # Only want to use the SelectSelector here.
        self.patch_default_selector()

        pipe = picklepipe.MarshalPipe(FakeSocket())
        self.addCleanup(pipe.close)

        self.assertRaises(picklepipe.PipeClosed, pipe.send_object, 'abc')
        self.assertIs(pipe.closed, True)