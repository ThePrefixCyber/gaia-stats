"""Fixed score landmarks shared with the live treemap's presentation contract."""
import math


def color(score):
    def blend(first, second, fraction):
        return '#' + ''.join(f'{math.floor(int(first[i:i+2],16)*(1-fraction)+int(second[i:i+2],16)*fraction+.5):02x}' for i in (1,3,5))
    if score < 0:return blend('#ff3b30','#7f1d1d',1-100/(100-score))
    if score <= 100:return blend('#ff3b30','#d1d5db',score/100)
    if score <= 150:return blend('#d1d5db','#5b8ac6',(score-100)/50)
    if score <= 200:return blend('#5b8ac6','#081d58',(score-150)/50)
    if score <= 225:return blend('#081d58','#166534',(score-200)/25)
    if score <= 300:return blend('#166534','#22c55e',(score-225)/75)
    return blend('#22c55e','#bbf7d0',1-100/(score-200))


def marker(values):
    observed=[value for value in values if isinstance(value,(int,float)) and math.isfinite(value)]
    low,high=min([0,*observed]),max([300,*observed])
    stops=sorted({low,0,50,100,150,200,225,300,high,*observed})
    return {'colors':values,'colorscale':[[(value-low)/(high-low),color(value)] for value in stops],
            'autocolorscale':False,'reversescale':False,'cauto':False,'cmin':low,'cmax':high,
            'colorbar':{'title':'Mean pre-bid VP','tickvals':([low] if low<0 else [])+[0,100,200,300]+([high] if high>300 else [])}}
