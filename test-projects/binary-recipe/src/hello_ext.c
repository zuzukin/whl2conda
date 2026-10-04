/* Minimal C extension module for the whl2conda build test fixture. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *hello(PyObject *self, PyObject *args) {
    return PyUnicode_FromString("hello");
}

static PyMethodDef methods[] = {
    {"hello", hello, METH_NOARGS, "Return a greeting."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "hello_ext", NULL, -1, methods,
};

PyMODINIT_FUNC PyInit_hello_ext(void) { return PyModule_Create(&module); }
