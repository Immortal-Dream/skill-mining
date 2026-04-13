# -*- coding: utf-8 -*-
"""
Created on Fri Feb  2 18:16:27 2024

@author: kanmani
"""

from Bio import SeqIO
record = SeqIO.parse(r'C:\Users\kanmani\HBB_2.fasta', 'fasta')
for elements in record:
    print(elements.id, len(elements.seq)) #elements.id or name(id alone)/description
    print(elements.description)