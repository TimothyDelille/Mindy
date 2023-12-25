import reminders.utils as utils
# this code is responsible for parsing the commands sent by Mindy:
# e.g. create(event_name, date, frequency)

# functions supported with their arguments, in correct order.
fn_name_to_args = {
    "create": ["event_name", "from_date", "to_date", "frequency"],
    "update": ["event_index", "event_name", "from_date", "to_date", "frequency"],
    "delete": ["event_index"],
    "fetch": [],
    "update_timezone": ["timezone"], # not in prompt but mindy likes to hallucinate commands.
}

def run(msg, user):
    str_params = parse(msg)
    params = []
    for fn, str_args in str_params:
        args, err = transform(fn, str_args, user)

        if err:
            return [], err  # fail early
        params.append((fn, args))
    return params, None

# todo: error handling is very unclear here.
# parse takes a msg
# and returns a list containing tuples (function name, list of arguments as strings).
def parse(msg):
    """
    msg format:

    ```
    create(event_name, time, frequency)
    delete(event_id)
    ```

    returns params (list: [(fn, {arg1: value, arg2: value})]), error (string)
    """
    params = list()

    # example: 'update(1, "go to sleep", "Tuesday, 2023-03-21 22:30:00", "once")'

    def fn_name(line):
        for func in fn_name_to_args.keys():
            if line.split("(")[0] == func:
                return func
        return None

    for s in msg.split("\n"):
        s = s.strip("- `")
        fn = fn_name(s)
        if not fn:
            continue

        if fn == "fetch":
            params.append(("fetch", []))
            continue

        args_str = s[s.find("(")+1:s.find(")")].strip()

        # extract everything between commas
        args = []
        curr_arg = ""
        begins_with_quote = False # used to keep track of quotes "..."
        quote_type = None
        for i, char in enumerate(args_str):
            if (char == "\"") or (char == "\'"):
                if not begins_with_quote:
                    begins_with_quote = True
                    quote_type = char
                else:
                    if quote_type == char:
                        begins_with_quote = False
                curr_arg += char
            elif char == ",":
                if begins_with_quote:
                    curr_arg += char
                else:
                    args.append(curr_arg.strip(" \"\'"))
                    curr_arg = ""
            else:
                curr_arg += char

            if i == len(args_str) - 1:
                args.append(curr_arg.strip(" \"\'"))
        params.append((fn, args))
    return params

# validate: takes in a function name `fn`, arguments `args` and a user dict
# and returns a map from argument name to parsed value if the argument is valid.
def transform(fn, args, user):
    valid_args = fn_name_to_args[fn]
    if len(valid_args) != len(args):
        return [], f"invalid number of arguments for function {fn}. Expected: {fn_name_to_args[fn]}, got: {args}"

    fn_params = {}
    for name, arg in zip(valid_args, args):
        if name == "event_index":
            try:
                fn_params["event_index"] = int(arg)
            except Exception as e:
                return [], f"can't convert event_id to int: {arg}. Exception: {e}"
        elif name == "from_date" or name == "to_date":
            fn_params[f"{name}_str"] = arg
            if name == "from_date" and arg == "none":
                return [], f"from_date can't be none, it should use the format {utils.TIME_FORMAT}"
            elif name == "to_date" and arg == "none":
                fn_params[name] = -1
                continue
            try:
                fn_params[name] = utils.usr_local_str_to_utc(arg, user["user_timezone"])
            except Exception as e:
                return [], f"can't parse event time: {arg}. Exception: {e}"
        elif name == "timezone":
            if utils.valid_timezone(arg):
                fn_params["timezone"] = arg
            else:
                return [], f"invalid timezone: {arg}. The timezone should be a valid input to the python `pytz` library."
        else: # string param that doesn't need post-processing (event_name, frequency)
            fn_params[name] = arg
    return fn_params, ""
