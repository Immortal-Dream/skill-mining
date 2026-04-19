# -*- coding: utf-8 -*-
"""
Created on Sun Feb  4 16:59:05 2024

@author: kanmani
"""

from Bio import SeqIO
record = SeqIO.parse(r'C:\Users\kanmani\HBB_human.gb', 'gb')
for element in record:
    '''print(element.id)
    print(element.annotations)
    for key in element.annotations.keys():
        print(key, ":", element.annotations[key])'''
    print(element.features)    
    for feature in element.features:
        if feature.type == 'CDS':  # to filter specific feature
            print(feature.type, feature.location,len(element.seq[feature.location.start: feature.location.end]))
            print(element.seq[feature.location.start:feature.location.end])
            
        
    