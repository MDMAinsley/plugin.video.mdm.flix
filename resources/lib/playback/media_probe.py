"""Small, bounded reads of MP4/Matroska metadata. Never decode media packets.

The reader needs an already playable HTTP file, not a magnet. Unsupported,
encrypted and non-seekable containers remain unknown. No URLs are persisted.
"""
import math
import re
import struct
import time
import urllib.request
import urllib.error
from urllib.parse import urljoin,urlsplit
from resources.lib.playback.files import web_url

class ProbeError(Exception):pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class HTTPReader:
    def __init__(self,url,seconds=4,cancel=lambda:False,max_bytes=1048576):
        if not web_url(url):raise ProbeError('unsupported')
        self.url=url;self.deadline=time.monotonic()+seconds;self.cancel=cancel
        self.max_bytes=max_bytes;self.bytes=0;self.requests=0;self.size=None;self.blocks={}
        self.opener=urllib.request.build_opener(NoRedirect())
    def check(self):
        if self.cancel():raise ProbeError('cancelled')
        if time.monotonic()>=self.deadline:raise ProbeError('timeout')
    def read(self,offset,count):
        self.check()
        if type(offset) is not int or offset<0 or count<0 or count>262144:raise ProbeError('bounds')
        if self.size is not None and offset+count>self.size:raise ProbeError('truncated')
        result=bytearray()
        while len(result)<count:
            at=offset+len(result);base=at//65536*65536
            if base not in self.blocks:self.load(base)
            block=self.blocks[base];part=block[at-base:at-base+count-len(result)]
            if not part:raise ProbeError('truncated')
            result.extend(part)
        return bytes(result)
    def load(self,start):
        self.check()
        if self.requests>=12 or self.bytes+65536>self.max_bytes:raise ProbeError('budget')
        end=start+65535
        if self.size is not None:end=min(end,self.size-1)
        response=None
        for redirect in range(3):
            self.check()
            if self.requests>=12:raise ProbeError('budget')
            req=urllib.request.Request(self.url,headers={'Range':'bytes={}-{}'.format(start,end),'Accept-Encoding':'identity','User-Agent':'MDM-Flix-Metadata/0.15.0'})
            self.requests+=1
            try:
                response=self.opener.open(req,timeout=max(.05,self.deadline-time.monotonic()));break
            except urllib.error.HTTPError as error:
                if error.code not in (301,302,303,307,308) or redirect==2:raise
                location=error.headers.get('Location');error.close()
                target=urljoin(self.url,location) if location else ''
                if not web_url(target) or urlsplit(self.url).scheme=='https' and urlsplit(target).scheme!='https':raise ProbeError('redirect')
                # Only Range/encoding/UA headers exist. No account headers,
                # cookies or original query parameters are copied to a target.
                self.url=target
        if response is None:raise ProbeError('redirect')
        with response:
            self.check()
            if response.headers.get('Content-Encoding','identity').lower()!='identity':raise ProbeError('encoding')
            match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if response.status!=206 or not match:raise ProbeError('range unavailable')
            first,last,total=map(int,match.groups())
            if first!=start or not first<=last<=end or total<=last or last!=min(end,total-1):raise ProbeError('bad range')
            if self.size is not None and total!=self.size:raise ProbeError('file changed')
            self.size=total;chunks=[];left=last-first+1
            while left:
                self.check();chunk=response.read1(min(left,16384))
                if not chunk:raise ProbeError('truncated')
                self.bytes+=len(chunk);left-=len(chunk);chunks.append(chunk)
            self.blocks[start]=b''.join(chunks)

def positive(value):
    return float(value) if type(value) in (int,float) and math.isfinite(value) and 0<value<=86400 else None

def atom(reader,offset,limit):
    if offset+8>limit:raise ProbeError('atom')
    raw=reader.read(offset,8);size,kind=struct.unpack('>I4s',raw);head=8
    if size==1:
        size=struct.unpack('>Q',reader.read(offset+8,8))[0];head=16
    elif size==0:size=limit-offset
    if size<head or offset+size>limit:raise ProbeError('atom bounds')
    return kind,offset+head,offset+size

def mp4(reader):
    # Follow declared atom boundaries, skipping mdat without downloading it.
    cursor=0;duration=None;chapters=[];stack=[];steps=0
    while steps<512:
        steps+=1;limit=stack[-1][1] if stack else reader.size
        if cursor>=limit:
            if not stack:break
            cursor=stack.pop()[1];continue
        kind,data,end=atom(reader,cursor,limit)
        if kind in (b'moov',b'udta'):
            stack.append((kind,end));cursor=data;continue
        if kind==b'mvhd':
            version=reader.read(data,1)[0]
            if version==0:
                scale,ticks=struct.unpack('>II',reader.read(data+12,8)) if end-data>=20 else (0,0)
            elif version==1:
                scale,ticks=struct.unpack('>IQ',reader.read(data+20,12)) if end-data>=32 else (0,0)
            else:scale,ticks=0,0
            duration=positive(ticks/scale) if scale else None
        elif kind==b'chpl' and end-data<=65536:
            raw=reader.read(data,end-data)
            # Nero chapter atom: FullBox + reserved uint32 + uint8 count.
            if len(raw)>=9 and raw[0]==1:
                pos=9
                for _ in range(min(raw[8],200)):
                    if pos+9>len(raw):break
                    start=struct.unpack('>Q',raw[pos:pos+8])[0]/10000000;length=raw[pos+8];pos+=9
                    if pos+length>len(raw):break
                    chapters.append({'time':start,'name':raw[pos:pos+length].decode('utf-8','replace')[:200]});pos+=length
        cursor=end
    return {'format':'MP4','duration':duration,'chapters':chapters}

def vint(reader,offset,identifier=False):
    first=reader.read(offset,1)[0];width=next((n for n in range(1,9) if first & (1<<(8-n))),0)
    if not width or identifier and width>4:raise ProbeError('vint')
    raw=reader.read(offset,width);value=int.from_bytes(raw,'big')
    if not identifier:
        value&=(1<<(width*7))-1
        if value==(1<<(width*7))-1:value=None
    return value,offset+width

def element(reader,offset,limit,unknown=False):
    tag,pos=vint(reader,offset,True);length,data=vint(reader,pos)
    if length is None:
        if not unknown:raise ProbeError('unknown size')
        return tag,data,limit
    end=data+length
    if end>limit:raise ProbeError('element bounds')
    return tag,data,end

def children(reader,start,end,maximum=2000):
    cursor=start;count=0
    while cursor<end:
        count+=1
        if count>maximum:raise ProbeError('element budget')
        tag,data,finish=element(reader,cursor,end);yield tag,data,finish;cursor=finish

def uint(reader,start,end):
    if not 1<=end-start<=8:raise ProbeError('integer')
    return int.from_bytes(reader.read(start,end-start),'big')

def chapter_atoms(reader,start,end,depth=0):
    if depth>5:raise ProbeError('chapter depth')
    marks=[]
    for tag,data,finish in children(reader,start,end,500):
        if tag!=0xB6:continue
        mark={'time':None,'name':''};enabled=True;hidden=False
        for key,a,b in children(reader,data,finish,100):
            if key==0x91:mark['time']=uint(reader,a,b)/1000000000
            elif key==0x4598:enabled=bool(uint(reader,a,b))
            elif key==0x98:hidden=bool(uint(reader,a,b))
            elif key==0x80:
                for name,x,y in children(reader,a,b,20):
                    if name==0x85 and y-x<=800 and not mark['name']:mark['name']=reader.read(x,y-x).decode('utf-8','replace')[:200]
        if enabled and not hidden and mark['time'] is not None:marks.append(mark)
        if len(marks)>200:raise ProbeError('chapter count')
    return marks

def mkv_chapters(reader,start,end):
    editions=[]
    for tag,data,finish in children(reader,start,end,100):
        if tag!=0x45B9:continue
        default=False;ordered=False
        for key,a,b in children(reader,data,finish,500):
            if key==0x45DB:default=bool(uint(reader,a,b))
            elif key==0x45DD:ordered=bool(uint(reader,a,b))
        if not ordered:editions.append((default,data,finish))
    if not editions:return []
    _,start,end=max(editions,key=lambda row:row[0]);return chapter_atoms(reader,start,end)

def mkv(reader):
    tag,data,end=element(reader,0,reader.size)
    if tag!=0x1A45DFA3:raise ProbeError('ebml')
    tag,base,limit=element(reader,end,reader.size,True)
    if tag!=0x18538067:raise ProbeError('segment')
    cursor=base;duration=None;chapters=[];targets={};visited=set();steps=0
    while steps<64:
        steps+=1
        if cursor>=limit or cursor in visited:break
        visited.add(cursor);tag,data,end=element(reader,cursor,limit,True)
        if tag==0x114D9B74:
            if end-data>65536:raise ProbeError('seekhead size')
            for entry,a,b in children(reader,data,end,100):
                if entry!=0x4DBB:continue
                target=None;position=None
                for key,x,y in children(reader,a,b,8):
                    if key==0x53AB:target=uint(reader,x,y)
                    elif key==0x53AC:position=uint(reader,x,y)
                if target in (0x1549A966,0x1043A770) and position is not None and base+position<limit:targets[target]=base+position
        elif tag==0x1549A966:
            if end-data>65536:raise ProbeError('info size')
            scale=1000000;ticks=None
            for key,a,b in children(reader,data,end,100):
                if key==0x2AD7B1:scale=uint(reader,a,b)
                elif key==0x4489 and b-a in (4,8):ticks=struct.unpack('>f' if b-a==4 else '>d',reader.read(a,b-a))[0]
            duration=positive(ticks*scale/1000000000) if ticks is not None else None
        elif tag==0x1043A770:
            if end-data>262144:raise ProbeError('chapters size')
            chapters=mkv_chapters(reader,data,end)
        if tag==0x1F43B675 or end==limit:
            remaining=[offset for offset in targets.values() if offset not in visited]
            if not remaining:break
            cursor=remaining[0]
        else:cursor=end
        if duration and chapters:break
    return {'format':'Matroska','duration':duration,'chapters':chapters}

def inspect(reader):
    head=reader.read(0,12)
    if head[:4]==b'\x1aE\xdf\xa3':result=mkv(reader)
    elif head[4:8] in (b'ftyp',b'moov',b'wide',b'free'):result=mp4(reader)
    else:raise ProbeError('unsupported')
    duration=result['duration'];marks=result['chapters']
    if duration:
        valid=[];previous=-1
        for mark in marks:
            at=mark['time']
            if not math.isfinite(at) or at<0 or at>=duration or at<=previous:continue
            previous=at;valid.append(mark)
        result['chapters']=valid
    else:result['chapters']=[]
    if not duration:raise ProbeError('duration unavailable')
    return result

def probe(url,seconds=4,cancel=lambda:False):
    reader=None
    try:
        reader=HTTPReader(url,seconds,cancel)
        result=inspect(reader);return dict(result,bytes=reader.bytes,requests=reader.requests,status='ready')
    except urllib.error.HTTPError as error:
        error.close();return {'status':'unavailable','bytes':reader.bytes if reader else 0,'requests':reader.requests if reader else 0}
    except (ProbeError,OSError,ValueError,OverflowError,struct.error):
        return {'status':'unavailable','bytes':reader.bytes if reader else 0,'requests':reader.requests if reader else 0}
