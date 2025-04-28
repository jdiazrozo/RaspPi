#!/usr/bin/env python

#Write previous averages in file
def write_previous_averages(previous_file, short, med, long):
    values = [str(short), str(med), str(long)]
    with open(previous_file, 'w+') as f:
        f.write(';'.join(values))
    return;

#Get previous averages from file
def get_previous_averages(previous_file):
    f = open(previous_file, 'r')
    data = f.read()
    values = data.split(';')
    f.close()
    values = [float(x) for x in values]
    return values