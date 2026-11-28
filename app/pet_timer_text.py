"""Conservative deterministic extraction; never infer owners or calendar recurrence."""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


def calendar_date(value):
    return datetime.strptime(value.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')


def clock_time(value):
    value=value.strip()
    match=re.fullmatch(r'(\d{1,2})\s*点(?:\s*(半|\d{1,2})\s*分?)?',value)
    if match:value=f"{match[1]}:{'30' if match[2]=='半' else match[2] or '00'}"
    return datetime.strptime(value,'%H:%M').strftime('%H:%M')


# These suffixes change the instant or clock interpretation. They must never be
# discarded as if they were merely the start of the task's instruction.
_CLOCK = r'(?:\d{1,2}:\d{2}|\d{1,2}\s*点(?:\s*(?:半|\d{1,2})\s*分?)?)'
_SUFFIX = (r'(?:[+−-]\s*\d|Z(?=$|[\s,，;；\u4e00-\u9fff])|'
           r'[ap]\.?m\.?(?=$|[\s,，;；\u4e00-\u9fff])|'
           r'(?:UTC|GMT|PST|PDT|EST|EDT|CST|CDT|MST|MDT|CET|CEST|JST|IST)(?=$|[+−\-\d\s,，;；\u4e00-\u9fff])|'
           r'[A-Za-z_+-]+/[A-Za-z_+/-]+|'
           r'(?-i:[A-Z]{2,6})(?=$|[\s,，;；\u4e00-\u9fff])|'
           r'时区|北京时间|上海时间|东京时间|当地时间|东\s*[一二三四五六七八九十\d]+\s*区|西\s*[一二三四五六七八九十\d]+\s*区|'
           r'上午|下午|晚上|早上|午前|午后)')


def unsupported_clock_suffix(value):
    prefix=r'^(?:(?:\d{4}-\d{1,2}-\d{1,2}\s+)|每天\s*)?'
    return re.match(prefix+_CLOCK+r'[\s,，;；.。:：]*[\[（(]?[\s,，;；.。:：]*'+_SUFFIX,value.strip(),re.IGNORECASE) is not None


def extract(text):
    """Only unambiguous fields. Conflicts stay missing even after a third value."""
    fields={};blocked=set();notices=[]
    def block(keys,notice):
        for key in keys:blocked.add(key);fields.pop(key,None)
        if notice not in notices:notices.append(notice)
    def assign(key,value):
        if key in blocked:return
        if key in fields and fields[key]!=value:
            block([key],'存在重复或冲突字段，请逐项重新确认。')
        else:fields[key]=value
    def assign_all(values):
        for key,value in values.items():assign(key,value)
    labels={'名称':'name','任务名称':'name','指令':'message','执行指令':'message','内容':'message','时区':'zone','日期':'first_date','时间':'time','频率':'frequency'}
    body=[]
    for part in re.split(r'[；;\n]+',text.strip()):
        match=re.fullmatch(r'\s*(任务名称|名称|执行指令|指令|内容|时区|日期|时间|频率)\s*[:：=]\s*(.*?)\s*',part)
        if not match:
            if part.strip():body.append(part.strip())
            continue
        key=labels[match[1]];value=match[2]
        try:
            if key=='first_date':assign(key,calendar_date(value))
            elif key=='time':
                if unsupported_clock_suffix(value):
                    block(['frequency','first_date','local_time','zone'],'时间包含暂不支持的偏移、AM/PM 或时区后缀，请分别填写 24 小时时间与 IANA 时区。')
                    continue
                pair=re.fullmatch(r'(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}:\d{2})',value)
                if pair:assign_all({'first_date':calendar_date(pair[1]),'local_time':clock_time(pair[2]),'frequency':'once'})
                else:assign('local_time',clock_time(value))
            elif key=='frequency':
                if value in ('单次','一次','once'):assign(key,'once')
                elif value in ('固定间隔','interval'):assign(key,'interval')
                else:body.append(value)
            else:assign(key,value)
        except ValueError:block(['first_date','local_time'] if key=='time' else [key],f'{match[1]}格式未能确认，请重新填写。')
    remaining='；'.join(body)
    # Boundaries prevent parsing 09:300 or 09:30:00 as a different valid time.
    time_token=r'(\d{1,2}:\d{2}|\d{1,2}\s*点(?:\s*(?:半|\d{1,2})\s*分?)?)(?!\s*[\d:：秒半一二三四五六七八九十零两刻整])'
    interval=re.match(r'^每隔\s*(\d+(?:\.\d+)?)\s*(分钟|小时|天)(?!\s*[\d半一二三四五六七八九十零两刻])(?:执行)?[，,\s]*',remaining)
    absolute=re.match(r'^(\d{4}-\d{1,2}-\d{1,2})\s+'+time_token+r'[，,\s]*',remaining)
    daily=re.match(r'^每天\s*'+time_token+r'[，,\s]*',remaining)
    candidate=interval or absolute or daily
    ambiguous_tail=bool(candidate and re.match(r'^(\d|[一二三四五六七八九十零两]|或|或者|至|到|和|及|与|并|且|[~～—–/、-]|内|后|左右|前后|之前|之后|以前|以后|至少|最多|大约|不早于|不晚于)',remaining[candidate.end():].lstrip(' \t\n,，;；.。:：')))
    try:
        if unsupported_clock_suffix(remaining):
            block(['frequency','first_date','local_time','zone'],'时间包含暂不支持的偏移、AM/PM 或时区后缀，请分别填写 24 小时时间与 IANA 时区；原文保留。')
        elif ambiguous_tail:
            block(['frequency','first_date','local_time','interval_value','interval_unit'],'时间包含范围、选择或不确定修饰，请给出一个明确计划；原文保留。')
        elif interval:
            amount=Decimal(interval[1]);factor={'分钟':1,'小时':60,'天':1440}[interval[2]]
            if amount*factor<Decimal('.25'):raise ValueError('间隔不能少于 15 秒')
            assign_all({'frequency':'interval','interval_value':str(amount*factor),'interval_unit':'minutes'})
            remaining=remaining[interval.end():]
        elif absolute:
            assign_all({'frequency':'once','first_date':calendar_date(absolute[1]),'local_time':clock_time(absolute[2])})
            remaining=remaining[absolute.end():]
        elif daily:
            assign('local_time',clock_time(daily[1]))
            block(['frequency'],'已识别每天固定时间，但当前创建接口只支持单次或固定间隔。请选择新的计划；不会自动改成每隔 24 小时。')
            remaining=remaining[daily.end():]
        elif re.match(r'^(每隔|每天|每周|工作日|明天|今天|后天|下周|\d{4}-|\d+\s*(分钟|小时)后)',remaining):
            notices.append('这段时间描述不能可靠转换，请明确选择计划并补充日期时间；原文保留。')
    except (ValueError,InvalidOperation):
        block(['frequency','first_date','local_time','interval_value','interval_unit'],'时间或间隔无效，请重新填写；原文保留。')
    # Unlabelled clauses may contain critical constraints, not just filler.
    if remaining and 'message' not in blocked:
        fields['message']='；'.join(filter(None,[fields.get('message',''),remaining]))
    if 'zone' in blocked:fields['zone']='' # do not silently fall back to the system zone
    return fields,' '.join(notices)
