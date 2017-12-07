import random

def int_generate(size):
    return random.randint(0,size)

def string_generate(size):
    word = ""

    for i in range(0,size):
        word += str(unichr(random.randint(97,122)))

    return word

def data_generate(_type, size):
    if _type == "int":
        return int_generate(size)
    elif _type == "string":
        return string_generate(size)

def main():
    table_cols = int(raw_input("Set the quantity of columns to be generate "))
    table_lines = int(raw_input("Set the quantity of lines to be gerated "))
    col_data = []
    col_properties = []

    for i in range(0, table_cols):
        _type = raw_input("Set the type of value: " + str(i) + " ")
        size = int(raw_input("Set the size of value: " + str(i) + " "))

        col_properties.append([_type, size])

    for j in range(0, table_lines):
        col_line = []
        for i in range(0, table_cols):
            random.seed(i + j)
            col_line.append(data_generate(col_properties[i][0], col_properties[i][1]))
        col_data.append(col_line)
    
    print col_data

    # for j in range(0, table_lines):
    #     for i in range(0, table_cols):
    #         random.seed(i)
    #         a = data_generate(col_properties[i][0], col_properties[i][1])
    #         print a
    #         col_line.append(a)
    #     print col_line
    #     col_data.append(col_line)

    
    # print col_line, "\n\n"
    # print col_data

main()