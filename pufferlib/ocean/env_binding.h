// Copyright (c) 2026 Robert Bosch GmbH
// SPDX-License-Identifier: AGPL-3.0

// This source code is derived from PufferDrive V2.0
// (https://github.com/Emerge-Lab/PufferDrive, version 1d864db)
// Copyright (c) PufferDrive authors, licensed under the MIT license,
// cf. 3rd-party-licenses.txt file in the root directory of this source tree.

#include "env_config.h"
#include <Python.h>
#include <numpy/arrayobject.h>

// Forward declarations for env-specific functions supplied by user
static int my_log(PyObject *dict, Log *log);
static int my_init(Env *env, PyObject *args, PyObject *kwargs);

static PyObject *my_shared(PyObject *self, PyObject *args, PyObject *kwargs);
#ifndef MY_SHARED
static PyObject *my_shared(PyObject *self, PyObject *args, PyObject *kwargs) { return NULL; }
#endif

static PyObject *my_get(PyObject *dict, Env *env);
#ifndef MY_GET
static PyObject *my_get(PyObject *dict, Env *env) { return NULL; }
#endif

static int my_put(Env *env, PyObject *args, PyObject *kwargs);
#ifndef MY_PUT
static int my_put(Env *env, PyObject *args, PyObject *kwargs) { return 0; }
#endif

#ifndef MY_METHODS
#define MY_METHODS {NULL, NULL, 0, NULL}
#endif

static Env *unpack_env(PyObject *args) {
    PyObject *handle_obj = PyTuple_GetItem(args, 0);
    if (!PyObject_TypeCheck(handle_obj, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "env_handle must be an integer");
        return NULL;
    }

    Env *env = (Env *)PyLong_AsVoidPtr(handle_obj);
    if (!env) {
        PyErr_SetString(PyExc_ValueError, "Invalid env handle");
        return NULL;
    }

    return env;
}

// Python function to initialize the environment
static PyObject *env_init(PyObject *self, PyObject *args, PyObject *kwargs) {
    if (PyTuple_Size(args) != 6) {
        PyErr_SetString(PyExc_TypeError, "Environment requires 5 arguments");
        return NULL;
    }

    Env *env = (Env *)calloc(1, sizeof(Env));
    if (!env) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate environment");
        return NULL;
    }

    PyObject *obs = PyTuple_GetItem(args, 0);
    if (!PyObject_TypeCheck(obs, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Observations must be a NumPy array");
        return NULL;
    }
    PyArrayObject *observations = (PyArrayObject *)obs;
    if (!PyArray_ISCONTIGUOUS(observations)) {
        PyErr_SetString(PyExc_ValueError, "Observations must be contiguous");
        return NULL;
    }
    env->observations = PyArray_DATA(observations);

    PyObject *act = PyTuple_GetItem(args, 1);
    if (!PyObject_TypeCheck(act, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Actions must be a NumPy array");
        return NULL;
    }
    PyArrayObject *actions = (PyArrayObject *)act;
    if (!PyArray_ISCONTIGUOUS(actions)) {
        PyErr_SetString(PyExc_ValueError, "Actions must be contiguous");
        return NULL;
    }
    env->actions = PyArray_DATA(actions);
    if (PyArray_ITEMSIZE(actions) == sizeof(double)) {
        PyErr_SetString(PyExc_ValueError, "Action tensor passed as float64 (pass np.float32 buffer)");
        return NULL;
    }

    PyObject *rew = PyTuple_GetItem(args, 2);
    if (!PyObject_TypeCheck(rew, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Rewards must be a NumPy array");
        return NULL;
    }
    PyArrayObject *rewards = (PyArrayObject *)rew;
    if (!PyArray_ISCONTIGUOUS(rewards)) {
        PyErr_SetString(PyExc_ValueError, "Rewards must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(rewards) != 1) {
        PyErr_SetString(PyExc_ValueError, "Rewards must be 1D");
        return NULL;
    }
    env->rewards = PyArray_DATA(rewards);

    PyObject *term = PyTuple_GetItem(args, 3);
    if (!PyObject_TypeCheck(term, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Terminals must be a NumPy array");
        return NULL;
    }
    PyArrayObject *terminals = (PyArrayObject *)term;
    if (!PyArray_ISCONTIGUOUS(terminals)) {
        PyErr_SetString(PyExc_ValueError, "Terminals must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(terminals) != 1) {
        PyErr_SetString(PyExc_ValueError, "Terminals must be 1D");
        return NULL;
    }
    env->terminals = PyArray_DATA(terminals);

    PyObject *trunc = PyTuple_GetItem(args, 4);
    if (!PyObject_TypeCheck(trunc, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Truncations must be a NumPy array");
        return NULL;
    }
    PyArrayObject *truncations = (PyArrayObject *)trunc;
    if (!PyArray_ISCONTIGUOUS(truncations)) {
        PyErr_SetString(PyExc_ValueError, "Truncations must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(truncations) != 1) {
        PyErr_SetString(PyExc_ValueError, "Truncations must be 1D");
        return NULL;
    }
    env->truncations = PyArray_DATA(truncations);

    PyObject *seed_arg = PyTuple_GetItem(args, 5);
    if (!PyObject_TypeCheck(seed_arg, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "seed must be an integer");
        return NULL;
    }
    int seed = PyLong_AsLong(seed_arg);

    // Assumes each process has the same number of environments
    srand(seed);

    // If kwargs is NULL, create a new dictionary
    if (kwargs == NULL) {
        kwargs = PyDict_New();
    } else {
        Py_INCREF(kwargs); // We need to increment the reference since we'll be modifying it
    }

    // Add the seed to kwargs
    PyObject *py_seed = PyLong_FromLong(seed);
    if (PyDict_SetItemString(kwargs, "seed", py_seed) < 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to set seed in kwargs");
        Py_DECREF(py_seed);
        Py_DECREF(kwargs);
        return NULL;
    }
    Py_DECREF(py_seed);

    PyObject *empty_args = PyTuple_New(0);
    my_init(env, empty_args, kwargs);
    Py_DECREF(kwargs);
    if (PyErr_Occurred()) {
        return NULL;
    }

    return PyLong_FromVoidPtr(env);
}

// Python function to reset the environment
static PyObject *env_reset(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "env_reset requires 2 arguments");
        return NULL;
    }

    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }
    c_reset(env);
    Py_RETURN_NONE;
}

// Python function to step the environment
static PyObject *env_step(PyObject *self, PyObject *args) {
    int num_args = PyTuple_Size(args);
    if (num_args != 1) {
        PyErr_SetString(PyExc_TypeError, "vec_render requires 1 argument");
        return NULL;
    }

    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }
    c_step(env);
    Py_RETURN_NONE;
}

// Python function to step the environment
static PyObject *env_render(PyObject *self, PyObject *args) {
    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }
    c_render(env);
    Py_RETURN_NONE;
}

// Python function to close the environment
static PyObject *env_close(PyObject *self, PyObject *args) {
    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }
    c_close(env);
    free(env);
    Py_RETURN_NONE;
}

static PyObject *env_get(PyObject *self, PyObject *args) {
    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }
    PyObject *dict = PyDict_New();
    my_get(dict, env);
    if (PyErr_Occurred()) {
        return NULL;
    }
    return dict;
}

static PyObject *env_put(PyObject *self, PyObject *args, PyObject *kwargs) {
    int num_args = PyTuple_Size(args);
    if (num_args != 1) {
        PyErr_SetString(PyExc_TypeError, "env_put requires 1 positional argument");
        return NULL;
    }

    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }

    PyObject *empty_args = PyTuple_New(0);
    my_put(env, empty_args, kwargs);
    if (PyErr_Occurred()) {
        return NULL;
    }

    Py_RETURN_NONE;
}

typedef struct {
    Env **envs;
    int num_envs;
} VecEnv;

static VecEnv *unpack_vecenv(PyObject *args) {
    PyObject *handle_obj = PyTuple_GetItem(args, 0);
    if (!PyObject_TypeCheck(handle_obj, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "env_handle must be an integer");
        return NULL;
    }

    VecEnv *vec = (VecEnv *)PyLong_AsVoidPtr(handle_obj);
    if (!vec) {
        PyErr_SetString(PyExc_ValueError, "Missing or invalid vec env handle");
        return NULL;
    }

    if (vec->num_envs <= 0) {
        PyErr_SetString(PyExc_ValueError, "Missing or invalid vec env handle");
        return NULL;
    }

    return vec;
}

static PyObject *vec_init(PyObject *self, PyObject *args, PyObject *kwargs) {
    if (PyTuple_Size(args) != 7) {
        PyErr_SetString(PyExc_TypeError, "vec_init requires 6 arguments");
        return NULL;
    }

    VecEnv *vec = (VecEnv *)calloc(1, sizeof(VecEnv));
    if (!vec) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate vec env");
        return NULL;
    }
    PyObject *num_envs_arg = PyTuple_GetItem(args, 5);
    if (!PyObject_TypeCheck(num_envs_arg, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "num_envs must be an integer");
        return NULL;
    }
    int num_envs = PyLong_AsLong(num_envs_arg);
    if (num_envs <= 0) {
        PyErr_SetString(PyExc_TypeError, "num_envs must be greater than 0");
        return NULL;
    }
    vec->num_envs = num_envs;
    vec->envs = (Env **)calloc(num_envs, sizeof(Env *));
    if (!vec->envs) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate vec env");
        return NULL;
    }

    PyObject *seed_obj = PyTuple_GetItem(args, 6);
    if (!PyObject_TypeCheck(seed_obj, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "seed must be an integer");
        return NULL;
    }
    int seed = PyLong_AsLong(seed_obj);

    PyObject *obs = PyTuple_GetItem(args, 0);
    if (!PyObject_TypeCheck(obs, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Observations must be a NumPy array");
        return NULL;
    }
    PyArrayObject *observations = (PyArrayObject *)obs;
    if (!PyArray_ISCONTIGUOUS(observations)) {
        PyErr_SetString(PyExc_ValueError, "Observations must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(observations) < 2) {
        PyErr_SetString(PyExc_ValueError, "Batched Observations must be at least 2D");
        return NULL;
    }

    PyObject *act = PyTuple_GetItem(args, 1);
    if (!PyObject_TypeCheck(act, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Actions must be a NumPy array");
        return NULL;
    }
    PyArrayObject *actions = (PyArrayObject *)act;
    if (!PyArray_ISCONTIGUOUS(actions)) {
        PyErr_SetString(PyExc_ValueError, "Actions must be contiguous");
        return NULL;
    }
    if (PyArray_ITEMSIZE(actions) == sizeof(double)) {
        PyErr_SetString(PyExc_ValueError, "Action tensor passed as float64 (pass np.float32 buffer)");
        return NULL;
    }

    PyObject *rew = PyTuple_GetItem(args, 2);
    if (!PyObject_TypeCheck(rew, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Rewards must be a NumPy array");
        return NULL;
    }
    PyArrayObject *rewards = (PyArrayObject *)rew;
    if (!PyArray_ISCONTIGUOUS(rewards)) {
        PyErr_SetString(PyExc_ValueError, "Rewards must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(rewards) != 1) {
        PyErr_SetString(PyExc_ValueError, "Rewards must be 1D");
        return NULL;
    }

    PyObject *term = PyTuple_GetItem(args, 3);
    if (!PyObject_TypeCheck(term, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Terminals must be a NumPy array");
        return NULL;
    }
    PyArrayObject *terminals = (PyArrayObject *)term;
    if (!PyArray_ISCONTIGUOUS(terminals)) {
        PyErr_SetString(PyExc_ValueError, "Terminals must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(terminals) != 1) {
        PyErr_SetString(PyExc_ValueError, "Terminals must be 1D");
        return NULL;
    }

    PyObject *trunc = PyTuple_GetItem(args, 4);
    if (!PyObject_TypeCheck(trunc, &PyArray_Type)) {
        PyErr_SetString(PyExc_TypeError, "Truncations must be a NumPy array");
        return NULL;
    }
    PyArrayObject *truncations = (PyArrayObject *)trunc;
    if (!PyArray_ISCONTIGUOUS(truncations)) {
        PyErr_SetString(PyExc_ValueError, "Truncations must be contiguous");
        return NULL;
    }
    if (PyArray_NDIM(truncations) != 1) {
        PyErr_SetString(PyExc_ValueError, "Truncations must be 1D");
        return NULL;
    }

    // If kwargs is NULL, create a new dictionary
    if (kwargs == NULL) {
        kwargs = PyDict_New();
    } else {
        Py_INCREF(kwargs); // We need to increment the reference since we'll be modifying it
    }

    for (int i = 0; i < num_envs; i++) {
        Env *env = (Env *)calloc(1, sizeof(Env));
        if (!env) {
            PyErr_SetString(PyExc_MemoryError, "Failed to allocate environment");
            Py_DECREF(kwargs);
            return NULL;
        }
        vec->envs[i] = env;

        // // Make sure the log is initialized to 0
        memset(&env->log, 0, sizeof(Log));

        env->observations = (void *)((char *)PyArray_DATA(observations) + i * PyArray_STRIDE(observations, 0));
        env->actions = (void *)((char *)PyArray_DATA(actions) + i * PyArray_STRIDE(actions, 0));
        env->rewards = (void *)((char *)PyArray_DATA(rewards) + i * PyArray_STRIDE(rewards, 0));
        env->terminals = (void *)((char *)PyArray_DATA(terminals) + i * PyArray_STRIDE(terminals, 0));
        env->truncations = (void*)((char*)PyArray_DATA(truncations) + i*PyArray_STRIDE(truncations, 0));

        // Assumes each process has the same number of environments
        int env_seed = i + seed * vec->num_envs;
        srand(env_seed);

        // Add the seed to kwargs for this environment
        PyObject *py_seed = PyLong_FromLong(env_seed);
        if (PyDict_SetItemString(kwargs, "seed", py_seed) < 0) {
            PyErr_SetString(PyExc_RuntimeError, "Failed to set seed in kwargs");
            Py_DECREF(py_seed);
            Py_DECREF(kwargs);
            return NULL;
        }
        Py_DECREF(py_seed);

        PyObject *empty_args = PyTuple_New(0);
        my_init(env, empty_args, kwargs);
        if (PyErr_Occurred()) {
            return NULL;
        }
    }

    Py_DECREF(kwargs);
    return PyLong_FromVoidPtr(vec);
}

// Python function to close the environment
static PyObject *vectorize(PyObject *self, PyObject *args) {
    int num_envs = PyTuple_Size(args);
    if (num_envs == 0) {
        PyErr_SetString(PyExc_TypeError, "make_vec requires at least 1 env id");
        return NULL;
    }

    VecEnv *vec = (VecEnv *)calloc(1, sizeof(VecEnv));
    if (!vec) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate vec env");
        return NULL;
    }

    vec->envs = (Env **)calloc(num_envs, sizeof(Env *));
    if (!vec->envs) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate vec env");
        return NULL;
    }

    vec->num_envs = num_envs;
    for (int i = 0; i < num_envs; i++) {
        PyObject *handle_obj = PyTuple_GetItem(args, i);
        if (!PyObject_TypeCheck(handle_obj, &PyLong_Type)) {
            PyErr_SetString(PyExc_TypeError,
                            "Env ids must be integers. Pass them as separate args with *env_ids, not as a list.");
            return NULL;
        }
        vec->envs[i] = (Env *)PyLong_AsVoidPtr(handle_obj);
    }

    return PyLong_FromVoidPtr(vec);
}

static PyObject *vec_reset(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "vec_reset requires 2 arguments");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(args);
    if (!vec) {
        return NULL;
    }

    PyObject *seed_arg = PyTuple_GetItem(args, 1);
    if (!PyObject_TypeCheck(seed_arg, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "seed must be an integer");
        return NULL;
    }
    int seed = PyLong_AsLong(seed_arg);

    for (int i = 0; i < vec->num_envs; i++) {
        // Assumes each process has the same number of environments
        srand(i + seed * vec->num_envs);
        c_reset(vec->envs[i]);
    }
    Py_RETURN_NONE;
}

static PyObject *vec_step(PyObject *self, PyObject *arg) {
    int num_args = PyTuple_Size(arg);
    if (num_args != 1) {
        PyErr_SetString(PyExc_TypeError, "vec_step requires 1 argument");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(arg);
    if (!vec) {
        return NULL;
    }

    for (int i = 0; i < vec->num_envs; i++) {
        c_step(vec->envs[i]);
    }
    Py_RETURN_NONE;
}

static PyObject *vec_render(PyObject *self, PyObject *args) {
    int num_args = PyTuple_Size(args);
    if (num_args != 2) {
        PyErr_SetString(PyExc_TypeError, "vec_render requires 2 arguments");
        return NULL;
    }

    VecEnv *vec = (VecEnv *)PyLong_AsVoidPtr(PyTuple_GetItem(args, 0));
    if (!vec) {
        PyErr_SetString(PyExc_ValueError, "Invalid vec_env handle");
        return NULL;
    }

    PyObject *env_id_arg = PyTuple_GetItem(args, 1);
    if (!PyObject_TypeCheck(env_id_arg, &PyLong_Type)) {
        PyErr_SetString(PyExc_TypeError, "env_id must be an integer");
        return NULL;
    }
    int env_id = PyLong_AsLong(env_id_arg);

    c_render(vec->envs[env_id]);
    Py_RETURN_NONE;
}

static int assign_to_dict(PyObject *dict, char *key, float value) {
    PyObject *v = PyFloat_FromDouble(value);
    if (v == NULL) {
        PyErr_SetString(PyExc_TypeError, "Failed to convert log value");
        return 1;
    }
    if (PyDict_SetItemString(dict, key, v) < 0) {
        PyErr_SetString(PyExc_TypeError, "Failed to set log value");
        return 1;
    }
    Py_DECREF(v);
    return 0;
}

static PyObject *vec_log(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "vec_log requires 2 arguments");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(args);
    if (!vec) {
        return NULL;
    }

    // Iterates over logs one float at a time. Will break
    // horribly if Log has non-float data.
    PyObject *num_agents_arg = PyTuple_GetItem(args, 1);
    float num_agents = (float)PyLong_AsLong(num_agents_arg);

    Log aggregate = {0};
    int num_keys = sizeof(Log) / sizeof(float);
    for (int i = 0; i < vec->num_envs; i++) {
        Env *env = vec->envs[i];
        for (int j = 0; j < num_keys; j++) {
            ((float *)&aggregate)[j] += ((float *)&env->log)[j];
        }
    }

    PyObject *dict = PyDict_New();

    // Only log if we have at least num_agents worth of data
    if (aggregate.n < num_agents) {
        return dict;
    }

    // Got enough data. Reset logs and return metrics
    for (int i = 0; i < vec->num_envs; i++) {
        Env *env = vec->envs[i];
        for (int j = 0; j < num_keys; j++) {
            ((float *)&env->log)[j] = 0.0f;
        }
    }

    float n = aggregate.n;

    // Average across agents
    for (int i = 0; i < num_keys; i++) {
        ((float *)&aggregate)[i] /= n;
    }

    // Compute completion_rate from aggregated counts
    aggregate.completion_rate = aggregate.goals_reached_this_episode / aggregate.goals_sampled_this_episode;

    // User populates dict
    my_log(dict, &aggregate);
    assign_to_dict(dict, "n", n);

    return dict;
}

static PyObject *vec_close(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) {
        return NULL;
    }

    for (int i = 0; i < vec->num_envs; i++) {
        c_close(vec->envs[i]);
        free(vec->envs[i]);
    }
    free(vec->envs);
    free(vec);
    Py_RETURN_NONE;
}

static PyObject *get_global_agent_state(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 7) {
        PyErr_SetString(PyExc_TypeError, "get_global_agent_state requires 7 arguments");
        return NULL;
    }

    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }

    Drive *drive = (Drive *)env; // Cast to Drive*

    // Get the numpy arrays from arguments
    PyObject *x_arr = PyTuple_GetItem(args, 1);
    PyObject *y_arr = PyTuple_GetItem(args, 2);
    PyObject *z_arr = PyTuple_GetItem(args, 3);
    PyObject *heading_arr = PyTuple_GetItem(args, 4);
    PyObject *id_arr = PyTuple_GetItem(args, 5);
    PyObject *length_arr = PyTuple_GetItem(args, 6);
    PyObject *width_arr = PyTuple_GetItem(args, 7);

    if (!PyArray_Check(x_arr) || !PyArray_Check(y_arr) || !PyArray_Check(z_arr) || !PyArray_Check(heading_arr) ||
        !PyArray_Check(id_arr) || !PyArray_Check(length_arr) || !PyArray_Check(width_arr)) {
        PyErr_SetString(PyExc_TypeError, "All output arrays must be NumPy arrays");
        return NULL;
    }

    float *x_data = (float *)PyArray_DATA((PyArrayObject *)x_arr);
    float *y_data = (float *)PyArray_DATA((PyArrayObject *)y_arr);
    float *z_data = (float *)PyArray_DATA((PyArrayObject *)z_arr);
    float *heading_data = (float *)PyArray_DATA((PyArrayObject *)heading_arr);
    int *id_data = (int *)PyArray_DATA((PyArrayObject *)id_arr);
    float *length_data = (float *)PyArray_DATA((PyArrayObject *)length_arr);
    float *width_data = (float *)PyArray_DATA((PyArrayObject *)width_arr);

    c_get_global_agent_state(drive, x_data, y_data, z_data, heading_data, id_data, length_data, width_data);

    Py_RETURN_NONE;
}
static PyObject *vec_get_global_agent_state(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 8) {
        PyErr_SetString(PyExc_TypeError, "vec_get_global_agent_state requires 8 arguments");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(args);
    if (!vec) {
        return NULL;
    }

    // Get the numpy arrays from arguments
    PyObject *x_arr = PyTuple_GetItem(args, 1);
    PyObject *y_arr = PyTuple_GetItem(args, 2);
    PyObject *z_arr = PyTuple_GetItem(args, 3);
    PyObject *heading_arr = PyTuple_GetItem(args, 4);
    PyObject *id_arr = PyTuple_GetItem(args, 5);
    PyObject *length_arr = PyTuple_GetItem(args, 6);
    PyObject *width_arr = PyTuple_GetItem(args, 7);

    if (!PyArray_Check(x_arr) || !PyArray_Check(y_arr) || !PyArray_Check(z_arr) || !PyArray_Check(heading_arr) ||
        !PyArray_Check(id_arr) || !PyArray_Check(length_arr) || !PyArray_Check(width_arr)) {
        PyErr_SetString(PyExc_TypeError, "All output arrays must be NumPy arrays");
        return NULL;
    }

    PyArrayObject *x_array = (PyArrayObject *)x_arr;
    PyArrayObject *y_array = (PyArrayObject *)y_arr;
    PyArrayObject *z_array = (PyArrayObject *)z_arr;
    PyArrayObject *heading_array = (PyArrayObject *)heading_arr;
    PyArrayObject *id_array = (PyArrayObject *)id_arr;
    PyArrayObject *length_array = (PyArrayObject *)length_arr;
    PyArrayObject *width_array = (PyArrayObject *)width_arr;

    // Get base pointers to the arrays
    float *x_base = (float *)PyArray_DATA(x_array);
    float *y_base = (float *)PyArray_DATA(y_array);
    float *z_base = (float *)PyArray_DATA(z_array);
    float *heading_base = (float *)PyArray_DATA(heading_array);
    int *id_base = (int *)PyArray_DATA(id_array);
    float *length_base = (float *)PyArray_DATA(length_array);
    float *width_base = (float *)PyArray_DATA(width_array);

    // Iterate through environments and write to correct offsets
    int offset = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];

        // Write to the arrays at the current offset
        c_get_global_agent_state(drive, &x_base[offset], &y_base[offset], &z_base[offset], &heading_base[offset],
                                 &id_base[offset], &length_base[offset], &width_base[offset]);

        // Move offset forward by the number of agents in this environment
        offset += drive->active_agent_count;
    }

    Py_RETURN_NONE;
}

static PyObject *vec_get_expert_agent_count(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int total = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        total += c_get_expert_agent_count((Drive *)vec->envs[i]);
    }
    return PyLong_FromLong(total);
}

static PyObject *vec_inject_active_agent(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_inject_active_agent requires keyword args");
        return NULL;
    }
    const char *keys[] = {"x", "y", "heading", "goal_x", "goal_y"};
    float vals[5] = {0};
    for (int k = 0; k < 5; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", keys[k]); return NULL; }
        vals[k] = (float)PyFloat_AsDouble(obj);
        if (PyErr_Occurred()) return NULL;
    }
    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) return NULL; }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }
    int rc = inject_active_agent((Drive *)vec->envs[env_idx],
                                 vals[0], vals[1], vals[2], vals[3], vals[4]);
    return PyLong_FromLong(rc == 0 ? 1 : 0);
}

static PyObject *vec_inject_static_agent(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_inject_static_agent requires keyword args");
        return NULL;
    }
    const char *keys[] = {"x", "y", "heading"};
    float vals[3] = {0};
    for (int k = 0; k < 3; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", keys[k]); return NULL; }
        vals[k] = (float)PyFloat_AsDouble(obj);
        if (PyErr_Occurred()) return NULL;
    }
    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) return NULL; }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }
    int rc = inject_static_agent((Drive *)vec->envs[env_idx], vals[0], vals[1], vals[2]);
    return PyLong_FromLong(rc == 0 ? 1 : 0);
}

static PyObject *vec_get_active_agent_count(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int total = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        total += c_get_active_agent_count((Drive *)vec->envs[i]);
    }
    return PyLong_FromLong(total);
}

static PyObject *vec_teleport_agent(PyObject *self, PyObject *args) {
    // args: (c_envs, env_idx, active_slot, world_x, world_y, heading, goal_x, goal_y)
    if (PyTuple_Size(args) != 8) {
        PyErr_SetString(PyExc_TypeError, "vec_teleport_agent requires 8 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int env_idx     = (int)PyLong_AsLong(PyTuple_GetItem(args, 1));
    int active_slot = (int)PyLong_AsLong(PyTuple_GetItem(args, 2));
    float world_x   = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 3));
    float world_y   = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 4));
    float heading   = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 5));
    float goal_x    = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 6));
    float goal_y    = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 7));
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range");
        return NULL;
    }
    c_teleport_agent((Drive *)vec->envs[env_idx], active_slot, world_x, world_y, heading, goal_x, goal_y);
    Py_RETURN_NONE;
}

static PyObject *vec_teleport_static_agent(PyObject *self, PyObject *args) {
    // args: (c_envs, env_idx, nonexpert_idx, world_x, world_y, heading)
    if (PyTuple_Size(args) != 6) {
        PyErr_SetString(PyExc_TypeError, "vec_teleport_static_agent requires 6 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int env_idx       = (int)PyLong_AsLong(PyTuple_GetItem(args, 1));
    int nonexpert_idx = (int)PyLong_AsLong(PyTuple_GetItem(args, 2));
    float world_x     = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 3));
    float world_y     = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 4));
    float heading     = (float)PyFloat_AsDouble(PyTuple_GetItem(args, 5));
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range");
        return NULL;
    }
    c_teleport_static_agent((Drive *)vec->envs[env_idx], nonexpert_idx, world_x, world_y, heading);
    Py_RETURN_NONE;
}

static PyObject *vec_detach_active_agent(PyObject *self, PyObject *args) {
    // args: (c_envs, env_idx, slot_idx)
    if (PyTuple_Size(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "vec_detach_active_agent requires 3 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int env_idx  = (int)PyLong_AsLong(PyTuple_GetItem(args, 1));
    int slot_idx = (int)PyLong_AsLong(PyTuple_GetItem(args, 2));
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range");
        return NULL;
    }
    c_detach_active_agent((Drive *)vec->envs[env_idx], slot_idx);
    Py_RETURN_NONE;
}

static PyObject *vec_detach_static_agent(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "vec_detach_static_agent requires 3 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int env_idx  = (int)PyLong_AsLong(PyTuple_GetItem(args, 1));
    int slot_idx = (int)PyLong_AsLong(PyTuple_GetItem(args, 2));
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range");
        return NULL;
    }
    c_detach_static_agent((Drive *)vec->envs[env_idx], slot_idx);
    Py_RETURN_NONE;
}

static PyObject *vec_detach_expert_agent(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "vec_detach_expert_agent requires 3 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int env_idx  = (int)PyLong_AsLong(PyTuple_GetItem(args, 1));
    int slot_idx = (int)PyLong_AsLong(PyTuple_GetItem(args, 2));
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range");
        return NULL;
    }
    c_detach_expert_agent((Drive *)vec->envs[env_idx], slot_idx);
    Py_RETURN_NONE;
}

static PyObject *vec_get_expert_agent_state(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 6) {
        PyErr_SetString(PyExc_TypeError, "vec_get_expert_agent_state requires 6 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;

    PyArrayObject *x_array   = (PyArrayObject *)PyTuple_GetItem(args, 1);
    PyArrayObject *y_array   = (PyArrayObject *)PyTuple_GetItem(args, 2);
    PyArrayObject *h_array   = (PyArrayObject *)PyTuple_GetItem(args, 3);
    PyArrayObject *l_array   = (PyArrayObject *)PyTuple_GetItem(args, 4);
    PyArrayObject *w_array   = (PyArrayObject *)PyTuple_GetItem(args, 5);

    float *x_base = (float *)PyArray_DATA(x_array);
    float *y_base = (float *)PyArray_DATA(y_array);
    float *h_base = (float *)PyArray_DATA(h_array);
    float *l_base = (float *)PyArray_DATA(l_array);
    float *w_base = (float *)PyArray_DATA(w_array);

    int offset = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        c_get_expert_agent_state(drive, &x_base[offset], &y_base[offset],
                                 &h_base[offset], &l_base[offset], &w_base[offset]);
        offset += c_get_expert_agent_count(drive);
    }
    Py_RETURN_NONE;
}

static PyObject *vec_get_agent_statuses(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "vec_get_agent_statuses requires 2 arguments: (c_envs, status_int32_array)");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;

    PyObject *status_obj = PyTuple_GetItem(args, 1);
    if (!PyArray_Check(status_obj)) {
        PyErr_SetString(PyExc_TypeError, "status array must be a NumPy int32 array");
        return NULL;
    }
    int *status_base = (int *)PyArray_DATA((PyArrayObject *)status_obj);

    int offset = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        c_get_agent_statuses(drive, &status_base[offset]);
        offset += drive->active_agent_count;
    }
    Py_RETURN_NONE;
}

static PyObject *vec_get_static_agent_count(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int total = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        total += c_get_static_agent_count((Drive *)vec->envs[i]);
    }
    return PyLong_FromLong(total);
}

static PyObject *vec_get_static_agent_state(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 6) {
        PyErr_SetString(PyExc_TypeError, "vec_get_static_agent_state requires 6 arguments");
        return NULL;
    }
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;

    PyArrayObject *x_array = (PyArrayObject *)PyTuple_GetItem(args, 1);
    PyArrayObject *y_array = (PyArrayObject *)PyTuple_GetItem(args, 2);
    PyArrayObject *h_array = (PyArrayObject *)PyTuple_GetItem(args, 3);
    PyArrayObject *l_array = (PyArrayObject *)PyTuple_GetItem(args, 4);
    PyArrayObject *w_array = (PyArrayObject *)PyTuple_GetItem(args, 5);

    float *x_base = (float *)PyArray_DATA(x_array);
    float *y_base = (float *)PyArray_DATA(y_array);
    float *h_base = (float *)PyArray_DATA(h_array);
    float *l_base = (float *)PyArray_DATA(l_array);
    float *w_base = (float *)PyArray_DATA(w_array);

    int offset = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        c_get_static_agent_state(drive, &x_base[offset], &y_base[offset],
                                 &h_base[offset], &l_base[offset], &w_base[offset]);
        offset += c_get_static_agent_count(drive);
    }
    Py_RETURN_NONE;
}

static PyObject *get_ground_truth_trajectories(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 7) {
        PyErr_SetString(PyExc_TypeError, "get_ground_truth_trajectories requires 7 arguments");
        return NULL;
    }

    Env *env = unpack_env(args);
    if (!env) {
        return NULL;
    }

    Drive *drive = (Drive *)env;

    // Get the numpy arrays from arguments
    PyObject *x_arr = PyTuple_GetItem(args, 1);
    PyObject *y_arr = PyTuple_GetItem(args, 2);
    PyObject *z_arr = PyTuple_GetItem(args, 3);
    PyObject *heading_arr = PyTuple_GetItem(args, 4);
    PyObject *valid_arr = PyTuple_GetItem(args, 5);
    PyObject *id_arr = PyTuple_GetItem(args, 6);
    PyObject *scenario_id_arr = PyTuple_GetItem(args, 7);

    if (!PyArray_Check(x_arr) || !PyArray_Check(y_arr) || !PyArray_Check(z_arr) || !PyArray_Check(heading_arr) ||
        !PyArray_Check(valid_arr) || !PyArray_Check(id_arr) || !PyArray_Check(scenario_id_arr)) {
        PyErr_SetString(PyExc_TypeError, "All output arrays must be NumPy arrays");
        return NULL;
    }

    float *x_data = (float *)PyArray_DATA((PyArrayObject *)x_arr);
    float *y_data = (float *)PyArray_DATA((PyArrayObject *)y_arr);
    float *z_data = (float *)PyArray_DATA((PyArrayObject *)z_arr);
    float *heading_data = (float *)PyArray_DATA((PyArrayObject *)heading_arr);
    int *valid_data = (int *)PyArray_DATA((PyArrayObject *)valid_arr);
    int *id_data = (int *)PyArray_DATA((PyArrayObject *)id_arr);
    int *scenario_id_data = (int *)PyArray_DATA((PyArrayObject *)scenario_id_arr);

    c_get_global_ground_truth_trajectories(drive, x_data, y_data, z_data, heading_data, valid_data, id_data,
                                           scenario_id_data);

    Py_RETURN_NONE;
}

static PyObject *vec_get_global_ground_truth_trajectories(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 8) {
        PyErr_SetString(PyExc_TypeError, "vec_get_global_ground_truth_trajectories requires 8 arguments");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(args);
    if (!vec) {
        return NULL;
    }

    // Get the numpy arrays from arguments
    PyObject *x_arr = PyTuple_GetItem(args, 1);
    PyObject *y_arr = PyTuple_GetItem(args, 2);
    PyObject *z_arr = PyTuple_GetItem(args, 3);
    PyObject *heading_arr = PyTuple_GetItem(args, 4);
    PyObject *valid_arr = PyTuple_GetItem(args, 5);
    PyObject *id_arr = PyTuple_GetItem(args, 6);
    PyObject *scenario_id_arr = PyTuple_GetItem(args, 7);

    if (!PyArray_Check(x_arr) || !PyArray_Check(y_arr) || !PyArray_Check(z_arr) || !PyArray_Check(heading_arr) ||
        !PyArray_Check(valid_arr) || !PyArray_Check(id_arr) || !PyArray_Check(scenario_id_arr)) {
        PyErr_SetString(PyExc_TypeError, "All output arrays must be NumPy arrays");
        return NULL;
    }

    PyArrayObject *x_array = (PyArrayObject *)x_arr;
    PyArrayObject *y_array = (PyArrayObject *)y_arr;
    PyArrayObject *z_array = (PyArrayObject *)z_arr;
    PyArrayObject *heading_array = (PyArrayObject *)heading_arr;
    PyArrayObject *valid_array = (PyArrayObject *)valid_arr;
    PyArrayObject *id_array = (PyArrayObject *)id_arr;
    PyArrayObject *scenario_id_array = (PyArrayObject *)scenario_id_arr;

    // Get base pointers to the arrays
    float *x_base = (float *)PyArray_DATA(x_array);
    float *y_base = (float *)PyArray_DATA(y_array);
    float *z_base = (float *)PyArray_DATA(z_array);
    float *heading_base = (float *)PyArray_DATA(heading_array);
    int *valid_base = (int *)PyArray_DATA(valid_array);
    int *id_base = (int *)PyArray_DATA(id_array);
    int *scenario_id_base = (int *)PyArray_DATA(scenario_id_array);

    // Get number of timesteps from array shape
    npy_intp *x_shape = PyArray_DIMS(x_array);
    int num_timesteps = x_shape[1]; // Second dimension for 2D arrays

    // Iterate through environments and write to correct offsets
    int agent_offset = 0; // Offset for 1D arrays (id, scenario_id)
    int traj_offset = 0;  // Offset for 2D arrays (x, y, z, heading, valid)

    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];

        c_get_global_ground_truth_trajectories(drive, &x_base[traj_offset], &y_base[traj_offset], &z_base[traj_offset],
                                               &heading_base[traj_offset], &valid_base[traj_offset],
                                               &id_base[agent_offset], &scenario_id_base[agent_offset]);

        // Move offsets forward
        agent_offset += drive->active_agent_count;
        traj_offset += drive->active_agent_count * num_timesteps;
    }

    Py_RETURN_NONE;
}

static PyObject *vec_get_road_edge_counts(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec)
        return NULL;

    int total_polylines = 0, total_points = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        int np, tp;
        c_get_road_edge_counts(drive, &np, &tp);
        total_polylines += np;
        total_points += tp;
    }
    return Py_BuildValue("(ii)", total_polylines, total_points);
}

static PyObject *vec_get_road_edge_polylines(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 5) {
        PyErr_SetString(PyExc_TypeError, "vec_get_road_edge_polylines requires 5 arguments");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(args);
    if (!vec)
        return NULL;

    PyObject *x_arr = PyTuple_GetItem(args, 1);
    PyObject *y_arr = PyTuple_GetItem(args, 2);
    PyObject *lengths_arr = PyTuple_GetItem(args, 3);
    PyObject *scenario_ids_arr = PyTuple_GetItem(args, 4);

    if (!PyArray_Check(x_arr) || !PyArray_Check(y_arr) || !PyArray_Check(lengths_arr) ||
        !PyArray_Check(scenario_ids_arr)) {
        PyErr_SetString(PyExc_TypeError, "All output arrays must be NumPy arrays");
        return NULL;
    }

    float *x_base = (float *)PyArray_DATA((PyArrayObject *)x_arr);
    float *y_base = (float *)PyArray_DATA((PyArrayObject *)y_arr);
    int *lengths_base = (int *)PyArray_DATA((PyArrayObject *)lengths_arr);
    int *scenario_ids_base = (int *)PyArray_DATA((PyArrayObject *)scenario_ids_arr);

    int poly_offset = 0, pt_offset = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        int np, tp;
        c_get_road_edge_counts(drive, &np, &tp);
        c_get_road_edge_polylines(drive, &x_base[pt_offset], &y_base[pt_offset], &lengths_base[poly_offset],
                                  &scenario_ids_base[poly_offset]);
        poly_offset += np;
        pt_offset += tp;
    }
    Py_RETURN_NONE;
}

static PyObject *vec_recompute_observations(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec)
        return NULL;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        compute_observations(drive);
    }
    Py_RETURN_NONE;
}

static PyObject *vec_reset_injections(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    for (int i = 0; i < vec->num_envs; i++)
        c_reset_injections((Drive *)vec->envs[i]);
    Py_RETURN_NONE;
}

static PyObject *vec_prepare_reserved_slots(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    for (int i = 0; i < vec->num_envs; i++)
        prepare_reserved_slots((Drive *)vec->envs[i]);
    Py_RETURN_NONE;
}

static PyObject *vec_prepare_demo_slots(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    for (int i = 0; i < vec->num_envs; i++)
        prepare_demo_slots((Drive *)vec->envs[i]);
    Py_RETURN_NONE;
}

static PyObject *vec_reset_demo_slots(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    for (int i = 0; i < vec->num_envs; i++)
        reset_demo_slots((Drive *)vec->envs[i]);
    Py_RETURN_NONE;
}

static PyObject *vec_inject_demo_active_agent(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_inject_demo_active_agent requires keyword args");
        return NULL;
    }
    const char *keys[] = {"x", "y", "heading", "goal_x", "goal_y"};
    float vals[5] = {0};
    for (int k = 0; k < 5; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", keys[k]); return NULL; }
        vals[k] = (float)PyFloat_AsDouble(obj);
        if (PyErr_Occurred()) return NULL;
    }
    float length = 0.0f, width = 0.0f;
    PyObject *lobj = PyDict_GetItemString(kwargs, "length");
    if (lobj) { length = (float)PyFloat_AsDouble(lobj); if (PyErr_Occurred()) return NULL; }
    PyObject *wobj = PyDict_GetItemString(kwargs, "width");
    if (wobj) { width  = (float)PyFloat_AsDouble(wobj); if (PyErr_Occurred()) return NULL; }
    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) return NULL; }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }
    int rc = inject_demo_active_agent((Drive *)vec->envs[env_idx],
                                      vals[0], vals[1], vals[2], vals[3], vals[4],
                                      length, width);
    return PyLong_FromLong(rc);
}

static PyObject *vec_inject_demo_static_agent(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_inject_demo_static_agent requires keyword args");
        return NULL;
    }
    const char *keys[] = {"x", "y", "heading"};
    float vals[3] = {0};
    for (int k = 0; k < 3; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", keys[k]); return NULL; }
        vals[k] = (float)PyFloat_AsDouble(obj);
        if (PyErr_Occurred()) return NULL;
    }
    float length = 0.0f, width = 0.0f;
    PyObject *lobj = PyDict_GetItemString(kwargs, "length");
    if (lobj) { length = (float)PyFloat_AsDouble(lobj); if (PyErr_Occurred()) return NULL; }
    PyObject *wobj = PyDict_GetItemString(kwargs, "width");
    if (wobj) { width  = (float)PyFloat_AsDouble(wobj); if (PyErr_Occurred()) return NULL; }
    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) return NULL; }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }
    int rc = inject_demo_static_agent((Drive *)vec->envs[env_idx], vals[0], vals[1], vals[2],
                                      length, width);
    return PyLong_FromLong(rc);
}

static PyObject *vec_inject_demo_expert_agent(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_inject_demo_expert_agent requires keyword args");
        return NULL;
    }
    const char *keys[] = {"x", "y", "heading"};
    float vals[3] = {0};
    for (int k = 0; k < 3; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", keys[k]); return NULL; }
        vals[k] = (float)PyFloat_AsDouble(obj);
        if (PyErr_Occurred()) return NULL;
    }
    float length = 0.0f, width = 0.0f;
    PyObject *lobj = PyDict_GetItemString(kwargs, "length");
    if (lobj) { length = (float)PyFloat_AsDouble(lobj); if (PyErr_Occurred()) return NULL; }
    PyObject *wobj = PyDict_GetItemString(kwargs, "width");
    if (wobj) { width  = (float)PyFloat_AsDouble(wobj); if (PyErr_Occurred()) return NULL; }
    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) return NULL; }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }
    int rc = inject_demo_expert_agent((Drive *)vec->envs[env_idx], vals[0], vals[1], vals[2],
                                      length, width);
    return PyLong_FromLong(rc);
}

static PyObject *vec_set_demo_expert_traj(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_set_demo_expert_traj requires keyword args");
        return NULL;
    }
    PyObject *sk_obj = PyDict_GetItemString(kwargs, "slot_k");
    if (!sk_obj) { PyErr_SetString(PyExc_TypeError, "missing kwarg 'slot_k'"); return NULL; }
    int slot_k = (int)PyLong_AsLong(sk_obj);
    if (PyErr_Occurred()) return NULL;

    const char *arr_keys[] = {"xs", "ys", "headings"};
    Py_buffer bufs[3];
    for (int k = 0; k < 3; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, arr_keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", arr_keys[k]); return NULL; }
        if (PyObject_GetBuffer(obj, &bufs[k], PyBUF_SIMPLE | PyBUF_FORMAT) < 0) return NULL;
    }
    int n = (int)(bufs[0].len / sizeof(float));
    if ((int)(bufs[1].len / sizeof(float)) != n || (int)(bufs[2].len / sizeof(float)) != n) {
        for (int k = 0; k < 3; k++) PyBuffer_Release(&bufs[k]);
        PyErr_SetString(PyExc_ValueError, "xs, ys, headings must have equal length");
        return NULL;
    }

    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) { for (int k=0;k<3;k++) PyBuffer_Release(&bufs[k]); return NULL; } }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        for (int k = 0; k < 3; k++) PyBuffer_Release(&bufs[k]);
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }

    set_demo_expert_traj((Drive *)vec->envs[env_idx], slot_k,
                         (float *)bufs[0].buf, (float *)bufs[1].buf, (float *)bufs[2].buf, n);
    for (int k = 0; k < 3; k++) PyBuffer_Release(&bufs[k]);
    Py_RETURN_NONE;
}

// Reposition a native expert in place by replacing its trajectory (keeps its slot/ID).
static PyObject *vec_teleport_expert_agent(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    if (!kwargs) {
        PyErr_SetString(PyExc_TypeError, "vec_teleport_expert_agent requires keyword args");
        return NULL;
    }
    PyObject *ei_obj = PyDict_GetItemString(kwargs, "expert_idx");
    if (!ei_obj) { PyErr_SetString(PyExc_TypeError, "missing kwarg 'expert_idx'"); return NULL; }
    int expert_idx = (int)PyLong_AsLong(ei_obj);
    if (PyErr_Occurred()) return NULL;

    const char *arr_keys[] = {"xs", "ys", "headings"};
    Py_buffer bufs[3];
    for (int k = 0; k < 3; k++) {
        PyObject *obj = PyDict_GetItemString(kwargs, arr_keys[k]);
        if (!obj) { PyErr_Format(PyExc_TypeError, "missing kwarg '%s'", arr_keys[k]); return NULL; }
        if (PyObject_GetBuffer(obj, &bufs[k], PyBUF_SIMPLE | PyBUF_FORMAT) < 0) return NULL;
    }
    int n = (int)(bufs[0].len / sizeof(float));
    if ((int)(bufs[1].len / sizeof(float)) != n || (int)(bufs[2].len / sizeof(float)) != n) {
        for (int k = 0; k < 3; k++) PyBuffer_Release(&bufs[k]);
        PyErr_SetString(PyExc_ValueError, "xs, ys, headings must have equal length");
        return NULL;
    }

    int env_idx = 0;
    PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
    if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) { for (int k=0;k<3;k++) PyBuffer_Release(&bufs[k]); return NULL; } }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        for (int k = 0; k < 3; k++) PyBuffer_Release(&bufs[k]);
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }

    c_teleport_expert_agent((Drive *)vec->envs[env_idx], expert_idx,
                            (float *)bufs[0].buf, (float *)bufs[1].buf, (float *)bufs[2].buf, n);
    for (int k = 0; k < 3; k++) PyBuffer_Release(&bufs[k]);
    Py_RETURN_NONE;
}

// Returns (used, total) for the demo shared slot pool of env_idx=0 (or specified env).
static PyObject *vec_get_demo_slots_info(PyObject *self, PyObject *args, PyObject *kwargs) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec) return NULL;
    int env_idx = 0;
    if (kwargs) {
        PyObject *eobj = PyDict_GetItemString(kwargs, "env_idx");
        if (eobj) { env_idx = (int)PyLong_AsLong(eobj); if (PyErr_Occurred()) return NULL; }
    }
    if (env_idx < 0 || env_idx >= vec->num_envs) {
        PyErr_SetString(PyExc_IndexError, "env_idx out of range"); return NULL;
    }
    Drive *d = (Drive *)vec->envs[env_idx];
    // Return (used, total) where total=MAX_AGENTS so Python computes free=total-used correctly.
    int n_free = d->demo_n_free_slots;
    return Py_BuildValue("(ii)", MAX_AGENTS - n_free, MAX_AGENTS);
}

static PyObject *vec_get_lane_counts(PyObject *self, PyObject *args) {
    VecEnv *vec = unpack_vecenv(args);
    if (!vec)
        return NULL;

    int total_polylines = 0, total_points = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        int np, tp;
        c_get_lane_counts(drive, &np, &tp);
        total_polylines += np;
        total_points += tp;
    }
    return Py_BuildValue("(ii)", total_polylines, total_points);
}

static PyObject *vec_get_lane_polylines(PyObject *self, PyObject *args) {
    if (PyTuple_Size(args) != 5) {
        PyErr_SetString(PyExc_TypeError, "vec_get_lane_polylines requires 5 arguments");
        return NULL;
    }

    VecEnv *vec = unpack_vecenv(args);
    if (!vec)
        return NULL;

    PyObject *x_arr = PyTuple_GetItem(args, 1);
    PyObject *y_arr = PyTuple_GetItem(args, 2);
    PyObject *lengths_arr = PyTuple_GetItem(args, 3);
    PyObject *scenario_ids_arr = PyTuple_GetItem(args, 4);

    if (!PyArray_Check(x_arr) || !PyArray_Check(y_arr) || !PyArray_Check(lengths_arr) ||
        !PyArray_Check(scenario_ids_arr)) {
        PyErr_SetString(PyExc_TypeError, "All output arrays must be NumPy arrays");
        return NULL;
    }

    float *x_base = (float *)PyArray_DATA((PyArrayObject *)x_arr);
    float *y_base = (float *)PyArray_DATA((PyArrayObject *)y_arr);
    int *lengths_base = (int *)PyArray_DATA((PyArrayObject *)lengths_arr);
    int *scenario_ids_base = (int *)PyArray_DATA((PyArrayObject *)scenario_ids_arr);

    int poly_offset = 0, pt_offset = 0;
    for (int i = 0; i < vec->num_envs; i++) {
        Drive *drive = (Drive *)vec->envs[i];
        int np, tp;
        c_get_lane_counts(drive, &np, &tp);
        c_get_lane_polylines(drive, &x_base[pt_offset], &y_base[pt_offset], &lengths_base[poly_offset],
                             &scenario_ids_base[poly_offset]);
        poly_offset += np;
        pt_offset += tp;
    }
    Py_RETURN_NONE;
}

static double unpack(PyObject *kwargs, char *key) {
    PyObject *val = PyDict_GetItemString(kwargs, key);
    if (val == NULL) {
        char error_msg[100];
        snprintf(error_msg, sizeof(error_msg), "Missing required keyword argument '%s'", key);
        PyErr_SetString(PyExc_TypeError, error_msg);
        return 1;
    }
    if (PyLong_Check(val)) {
        long out = PyLong_AsLong(val);
        if (out > INT_MAX || out < INT_MIN) {
            char error_msg[100];
            snprintf(error_msg, sizeof(error_msg), "Value %ld of integer argument %s is out of range", out, key);
            PyErr_SetString(PyExc_TypeError, error_msg);
            return 1;
        }
        // Cast on return. Safe because double can represent all 32-bit ints exactly
        return out;
    }
    if (PyFloat_Check(val)) {
        return PyFloat_AsDouble(val);
    }
    char error_msg[100];
    snprintf(error_msg, sizeof(error_msg), "Failed to unpack keyword %s as int", key);
    PyErr_SetString(PyExc_TypeError, error_msg);
    return 1;
}

static char *unpack_str(PyObject *kwargs, char *key) {
    PyObject *val = PyDict_GetItemString(kwargs, key);
    if (val == NULL) {
        char error_msg[100];
        snprintf(error_msg, sizeof(error_msg), "Missing required keyword argument '%s'", key);
        PyErr_SetString(PyExc_TypeError, error_msg);
        return NULL;
    }
    if (!PyUnicode_Check(val)) {
        char error_msg[100];
        snprintf(error_msg, sizeof(error_msg), "Keyword argument '%s' must be a string", key);
        PyErr_SetString(PyExc_TypeError, error_msg);
        return NULL;
    }
    const char *str_val = PyUnicode_AsUTF8(val);
    if (str_val == NULL) {
        // PyUnicode_AsUTF8 sets an error on failure
        return NULL;
    }
    char *ret = strdup(str_val);
    if (ret == NULL) {
        PyErr_SetString(PyExc_MemoryError, "strdup failed in unpack_str");
    }
    return ret;
}

// Method table
static PyMethodDef methods[] = {
    {"env_init", (PyCFunction)env_init, METH_VARARGS | METH_KEYWORDS,
     "Init environment with observation, action, reward, terminal, truncation arrays"},
    {"env_reset", env_reset, METH_VARARGS, "Reset the environment"},
    {"env_step", env_step, METH_VARARGS, "Step the environment"},
    {"env_render", env_render, METH_VARARGS, "Render the environment"},
    {"env_close", env_close, METH_VARARGS, "Close the environment"},
    {"env_get", env_get, METH_VARARGS, "Get the environment state"},
    {"env_put", (PyCFunction)env_put, METH_VARARGS | METH_KEYWORDS, "Put stuff into env"},
    {"vectorize", vectorize, METH_VARARGS, "Make a vector of environment handles"},
    {"vec_init", (PyCFunction)vec_init, METH_VARARGS | METH_KEYWORDS, "Initialize a vector of environments"},
    {"vec_reset", vec_reset, METH_VARARGS, "Reset the vector of environments"},
    {"vec_step", vec_step, METH_VARARGS, "Step the vector of environments"},
    {"vec_log", vec_log, METH_VARARGS, "Log the vector of environments"},
    {"vec_render", vec_render, METH_VARARGS, "Render the vector of environments"},
    {"vec_close", vec_close, METH_VARARGS, "Close the vector of environments"},
    {"shared", (PyCFunction)my_shared, METH_VARARGS | METH_KEYWORDS, "Shared state"},
    {"get_global_agent_state", get_global_agent_state, METH_VARARGS, "Get global agent state"},
    {"vec_get_global_agent_state", vec_get_global_agent_state, METH_VARARGS, "Get agent state from vectorized env"},
    {"vec_get_expert_agent_count", vec_get_expert_agent_count, METH_VARARGS, "Get total expert agent count from vectorized env"},
    {"vec_get_expert_agent_state", vec_get_expert_agent_state, METH_VARARGS, "Get expert (non-controlled) agent state from vectorized env"},
    {"vec_get_agent_statuses", vec_get_agent_statuses, METH_VARARGS, "Get per-agent status codes (0=running,1=paused,2=crashed,3=offroad,4=goal_reached)"},
    {"vec_get_static_agent_count", vec_get_static_agent_count, METH_VARARGS, "Get total static (parked) agent count from vectorized env"},
    {"vec_get_static_agent_state", vec_get_static_agent_state, METH_VARARGS, "Get static (parked) agent state from vectorized env"},
    {"vec_get_active_agent_count", vec_get_active_agent_count, METH_VARARGS, "Get total active (policy-controlled) agent count"},
    {"vec_teleport_agent", vec_teleport_agent, METH_VARARGS, "Teleport an active agent to a new position/heading/goal"},
    {"vec_teleport_static_agent", vec_teleport_static_agent, METH_VARARGS, "Reposition a non-expert static agent in place (keeps its slot/identity)"},
    {"vec_teleport_expert_agent", (PyCFunction)vec_teleport_expert_agent, METH_VARARGS | METH_KEYWORDS, "Reposition an expert agent in place by replacing its trajectory (keeps its slot/identity)"},
    {"vec_detach_active_agent", vec_detach_active_agent, METH_VARARGS, "Remove an active agent from the pool (frees a slot for demo injection in full scenes)"},
    {"vec_detach_static_agent", vec_detach_static_agent, METH_VARARGS, "Remove a non-expert static agent from the pool (frees a slot for demo injection)"},
    {"vec_detach_expert_agent", vec_detach_expert_agent, METH_VARARGS, "Remove an expert static agent from the pool (frees a slot for demo injection)"},
    {"vec_inject_active_agent", (PyCFunction)vec_inject_active_agent, METH_VARARGS | METH_KEYWORDS, "Inject a new policy-controlled agent (hijacks an inactive vehicle slot)"},
    {"vec_inject_static_agent", (PyCFunction)vec_inject_static_agent, METH_VARARGS | METH_KEYWORDS, "Inject a new non-moving static agent"},
    {"get_ground_truth_trajectories", get_ground_truth_trajectories, METH_VARARGS, "Get ground truth trajectories"},
    {"vec_get_global_ground_truth_trajectories", vec_get_global_ground_truth_trajectories, METH_VARARGS,
     "Get ground truth trajectories from vectorized env"},
    {"vec_get_road_edge_counts", vec_get_road_edge_counts, METH_VARARGS,
     "Get road edge polyline counts from vectorized env"},
    {"vec_get_road_edge_polylines", vec_get_road_edge_polylines, METH_VARARGS,
     "Get road edge polylines from vectorized env"},
    {"vec_recompute_observations", vec_recompute_observations, METH_VARARGS,
     "Recompute observations for all envs (call after set_goals to keep observations in sync)"},
    {"vec_reset_injections", vec_reset_injections, METH_VARARGS,
     "Restore agent counts to original post-init values, discarding all injected agents"},
    {"vec_prepare_reserved_slots", vec_prepare_reserved_slots, METH_VARARGS,
     "Pre-reserve N_INJECTION_RESERVE vehicle slots for robust injection (park them at -9000,-9000)"},
    {"vec_prepare_demo_slots", vec_prepare_demo_slots, METH_VARARGS,
     "Allocate MAX_AGENTS-num_actors shared demo slots (active/static/expert) parked at INVALID_POSITION"},
    {"vec_reset_demo_slots", vec_reset_demo_slots, METH_VARARGS,
     "Park all demo slots back to INVALID_POSITION (call before re-injecting user agents)"},
    {"vec_inject_demo_active_agent", (PyCFunction)vec_inject_demo_active_agent, METH_VARARGS | METH_KEYWORDS,
     "Promote a free shared demo slot to active agent; returns slot index k or -1 if full"},
    {"vec_inject_demo_static_agent", (PyCFunction)vec_inject_demo_static_agent, METH_VARARGS | METH_KEYWORDS,
     "Place a user static agent into a free shared demo slot; returns slot index k or -1 if full"},
    {"vec_inject_demo_expert_agent", (PyCFunction)vec_inject_demo_expert_agent, METH_VARARGS | METH_KEYWORDS,
     "Place a user expert agent into a free shared demo slot; returns slot_k or -1 if full"},
    {"vec_set_demo_expert_traj", (PyCFunction)vec_set_demo_expert_traj, METH_VARARGS | METH_KEYWORDS,
     "Write xs/ys/headings trajectory into demo slot slot_k (must be an expert slot)"},
    {"vec_get_demo_slots_info", (PyCFunction)vec_get_demo_slots_info, METH_VARARGS | METH_KEYWORDS,
     "Returns (used, total) for the shared demo slot pool"},
    {"vec_get_lane_counts", vec_get_lane_counts, METH_VARARGS,
     "Get lane polyline counts from vectorized env"},
    {"vec_get_lane_polylines", vec_get_lane_polylines, METH_VARARGS,
     "Get lane polylines from vectorized env"},
    MY_METHODS,
    {NULL, NULL, 0, NULL}};

// Module definition
static PyModuleDef module = {PyModuleDef_HEAD_INIT, "binding", NULL, -1, methods};

PyMODINIT_FUNC PyInit_binding(void) {
    import_array();
    PyObject *m = PyModule_Create(&module); // Changed variable name from 'module' to 'm'

    if (m == NULL) {
        return NULL;
    }

    // Make constants accessible from Python
    PyModule_AddIntConstant(m, "MAX_ROAD_SEGMENT_OBSERVATIONS", MAX_ROAD_SEGMENT_OBSERVATIONS);
    PyModule_AddIntConstant(m, "MAX_AGENTS", MAX_AGENTS);
    PyModule_AddIntConstant(m, "TRAJECTORY_LENGTH", TRAJECTORY_LENGTH);
    PyModule_AddIntConstant(m, "MAX_ENTITIES_PER_CELL", MAX_ENTITIES_PER_CELL);

    PyModule_AddIntConstant(m, "ROAD_FEATURES", ROAD_FEATURES);
    PyModule_AddIntConstant(m, "PARTNER_FEATURES", PARTNER_FEATURES);
    PyModule_AddIntConstant(m, "EGO_FEATURES_CLASSIC", EGO_FEATURES_CLASSIC);
    PyModule_AddIntConstant(m, "EGO_FEATURES_JERK", EGO_FEATURES_JERK);

    return m;
}
