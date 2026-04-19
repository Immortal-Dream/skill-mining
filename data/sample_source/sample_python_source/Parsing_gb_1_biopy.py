# -*- coding: utf-8 -*-
"""
Created on Sun Feb  4 18:33:32 2024

@author: kanmani
"""

from Bio import SeqIO
#file containing more than one gb
record = SeqIO .parse(r'C:\Users\kanmani\HBB.gb', 'gb')
for element in record:
       
   # print(element.annotations['organism']) #taxonomy
    #   print ('\n'.join(element.annotations.keys()))
    if 'references' in element.annotations.keys():
        for items in element.annotations['references']:
            #print(items.pubmed_id)
            print(items.title)
            