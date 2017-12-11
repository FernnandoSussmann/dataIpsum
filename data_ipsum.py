import random

def int_generate(size):
    return random.randint(0,size)

def string_generate(size):
    word = ""

    for i in range(0,size):
        word += str(unichr(random.randint(97,122)))

    return word

def float_generate(integer_size, decimal_size):
    _int = ""
    _decimals = ""

    for i in range(0, integer_size):
        _int += str(unichr(random.randint(48,57)))
    for i in range(0, decimal_size):
        _decimals += str(unichr(random.randint(48,57)))

    return float(_int + "." + _decimals)

def data_generate(settings):
    if settings[0] == "int":
        return int_generate(settings[1])
    elif settings[0] == "string":
        return string_generate(settings[1])
    elif  settings[0] == "float":
        return float_generate(settings[1], settings[2])

def main():
    table_cols = int(raw_input("Set the quantity of columns to be generate "))
    table_lines = int(raw_input("Set the quantity of lines to be gerated "))
    col_data = []
    col_properties = []

    for i in range(0, table_cols):
        settings = []
        settings.append(raw_input("Set the type of value " + str(i) + ": "))
        settings.append(int(raw_input("Set the size of value " + str(i) + ": ")))

        if settings[0] == "float":
            settings.append(int(raw_input("Set the number of decimals " + str(i) + ": ")))            

        col_properties.append([settings])

    for j in range(0, table_lines):
        col_line = []
        for i in range(0, table_cols):
            random.seed(i + j)
            col_line.append(data_generate(col_properties[i][0]))
        col_data.append(col_line)
    
    print col_data

main()