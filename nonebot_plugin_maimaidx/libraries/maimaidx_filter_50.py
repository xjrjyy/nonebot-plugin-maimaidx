import math
import traceback
import re
from typing import List, Optional, Tuple, Union, Callable

from nonebot.adapters.onebot.v11 import MessageSegment

from ..config import *
from .image import image_to_bytesio
from .maimaidx_api_data import maiApi
from .maimaidx_error import *
from .maimaidx_music import mai
from .maimaidx_chart_list_drawer import ChartListDrawer, ChartInfoGroup, ChartInfo, UserInfo, dxScore


class BaseFilterArg:
    def valid(self, _: ChartInfo) -> bool:
        raise NotImplementedError

class FilterArgDs(BaseFilterArg):
    def __init__(self, lower: Optional[float], upper: Optional[float]) -> None:
        self.lower = lower
        self.upper = upper
    def valid(self, info: ChartInfo) -> bool:
        if self.lower is not None and info.ds < self.lower:
            return False
        if self.upper is not None and info.ds > self.upper:
            return False
        return True

class FilterArgStar(BaseFilterArg):
    def __init__(self, lower: Optional[int], upper: Optional[int]) -> None:
        self.lower = lower
        self.upper = upper
    def valid(self, info: ChartInfo) -> bool:
        star = dxScore(info.dxScore / getTotalDxScore(info) * 100)[1]
        if self.lower is not None and star < self.lower:
            return False
        if self.upper is not None and star > self.upper:
            return False
        return True

class FilterArgAchievement(BaseFilterArg):
    def __init__(self, lower: Optional[float], upper: Optional[float]) -> None:
        self.lower = lower
        self.upper = upper
    def valid(self, info: ChartInfo) -> bool:
        if self.lower is not None and info.achievements < self.lower:
            return False
        if self.upper is not None and info.achievements > self.upper:
            return False
        return True

class FilterArgLevel(BaseFilterArg):
    def __init__(self, lower: Optional[int], upper: Optional[int]) -> None:
        self.lower = lower
        self.upper = upper
    def valid(self, info: ChartInfo) -> bool:
        if self.lower is not None and info.level_index < self.lower:
            return False
        if self.upper is not None and info.level_index > self.upper:
            return False
        return True

class FilterArgCategory(BaseFilterArg):
    def __init__(self, categories: List[str]) -> None:
        self.categories = categories
    def valid(self, info: ChartInfo) -> bool:
        music = mai.total_list.by_id(str(info.song_id))
        return category[music.basic_info.genre] in self.categories

def parse_filter_args(args: List[str]) -> Tuple[Callable[[ChartInfo], bool], Callable[[ChartInfo, ChartInfo], int]]:
    filter_list: List[BaseFilterArg] = []
    cmp_type: Tuple[str, Optional[str]] = ('ra', None)
    reverse = False

    def parse(prefix: str, arg: str, re_str: str) -> Tuple[Optional[str], Optional[str]]:
        result = re.match(f'^{prefix}[=＝]?(?P<value>{re_str})$', arg)
        if result:
            return result.group('value'), result.group('value')
        result = re.match(f'^{prefix}[=＝]?(?P<lower>{re_str})?[-~～](?P<upper>{re_str}$)?', arg)
        if result:
            return result.group('lower'), result.group('upper')
        raise ValueError(f'无法解析参数：{arg}')
    for arg in args:
        arg = arg.lower()
        if arg.startswith('diff') or arg.startswith('ds'):
            lower_str, upper_str = parse('(diff|ds)', arg, r'\d+(\.\d|\+)?')
            if lower_str:
                if lower_str.endswith('+'):
                    lower = float(lower_str[:-1]) + 0.7
                else:
                    lower = float(lower_str)
            else:
                lower = None
            if upper_str:
                if upper_str.endswith('+'):
                    upper = float(upper_str[:-1]) + 0.9
                elif '.' in upper_str:
                    upper = float(upper_str)
                else:
                    upper = float(upper_str) + 0.6
            else:
                upper = None
            filter_list.append(FilterArgDs(lower, upper))
        elif arg.startswith('star'):
            lower_str, upper_str = parse('star', arg, '[0-5]')
            lower = int(lower_str) if lower_str else None
            upper = int(upper_str) if upper_str else None
            filter_list.append(FilterArgStar(lower, upper))
        elif arg.startswith('achv'):
            lower_str, upper_str = parse('achv', arg, r'\d+(\.\d*)?')
            lower = float(lower_str) if lower_str else None
            upper = float(upper_str) if upper_str else None
            filter_list.append(FilterArgAchievement(lower, upper))
        elif arg.startswith('lv'):
            lower_str, upper_str = parse('lv', arg, '[绿黄红紫白]')
            level_labels = ['绿', '黄', '红', '紫', '白']
            lower = level_labels.index(lower_str) if lower_str else None
            upper = level_labels.index(upper_str) if upper_str else None
            filter_list.append(FilterArgLevel(lower, upper))
        elif arg.startswith('cat'):
            category_str = arg[3:]
            if category_str.startswith(('=', '＝')):
                category_str = category_str[1:]
            categories = [category.lower() for category in category_str.split('+,;＋，；')]
            for item in categories:
                if item not in category:
                    raise ValueError(f'未知谱面分类：{item}')
            filter_list.append(FilterArgCategory(categories))
        elif arg.startswith('cmp'):
            cmp_type_str = arg[3:]
            if cmp_type_str.startswith(('=', '＝')):
                cmp_type_str = cmp_type_str[1:]
            ATTRS = [
                'ra', 'achv', 'dxs', 'cun', 'suo',
                'diff', 'ds', 'bpm', 'fit',
                'tap', 'hold', 'slide', 'touch', 'break', 'note',
            ]
            attr_re = '|'.join(ATTRS)
            result = re.match(f'^(?P<num>{attr_re})(/(?P<den>(?<=/){attr_re}))?$', cmp_type_str)
            if result:
                cmp_type = (result.group('num'), result.group('den'))
            else:
                raise ValueError(f'未知排序方式：{cmp_type_str}')
        elif arg == 'rev':
            reverse = True
        else:
            raise ValueError(f'未知参数：{arg}')

    def filter(info: ChartInfo) -> bool:
        for f in filter_list:
            if not f.valid(info):
                return False
        return True
    def cmp(lhs: ChartInfo, rhs: ChartInfo) -> int:
        def chart_attr(chart_info: ChartInfo, attr: Optional[str]) -> float:
            if attr is None:
                return 1
            music = mai.total_list.by_id(str(chart_info.song_id))
            if attr == 'ra':
                return chart_info.ra
            elif attr == 'achv':
                return chart_info.achievements
            elif attr == 'dxs':
                return chart_info.dxScore / getTotalDxScore(chart_info)
            elif attr == 'cun':
                return -getSuoScore(chart_info)
            elif attr == 'suo':
                return getSuoScore(chart_info)
            elif attr in ['diff', 'ds']:
                return chart_info.ds
            elif attr == 'bpm':
                return music.basic_info.bpm
            chart = music.charts[chart_info.level_index]
            if attr == 'fit':
                if  music.stats is None:
                    return 0
                stat = music.stats[chart_info.level_index]
                if stat is None:
                    return 0
                return stat.fit_diff - chart_info.ds
            elif attr == 'tap':
                return chart.notes.tap
            elif attr == 'hold':
                return chart.notes.hold
            elif attr == 'slide':
                return chart.notes.slide
            elif attr == 'touch':
                return chart.notes.touch if hasattr(chart.notes, 'touch') else 0
            elif attr == 'break':
                return chart.notes.brk
            elif attr == 'note':
                return sum(chart.notes)
            else:
                raise Exception(f'未知属性：{attr}')
        lhs_rate = chart_attr(lhs, cmp_type[0]) / max(chart_attr(lhs, cmp_type[1]), 0.0001)
        rhs_rate = chart_attr(rhs, cmp_type[0]) / max(chart_attr(rhs, cmp_type[1]), 0.0001)
        result = (rhs_rate - lhs_rate) * (-1 if reverse else 1)
        if result < 0:
            return -1
        elif result > 0:
            return 1
        else:
            return 0

    return (filter, cmp)

def getTotalDxScore(info: ChartInfo) -> int:
    return sum(mai.total_list.by_id(str(info.song_id)).charts[info.level_index].notes) * 3

def getSuoScore(info: ChartInfo) -> float:
    if info.achievements == 101:
        goal = 100.5
    elif info.achievements >= 97:
        goal = math.floor(info.achievements * 2) / 2
    elif info.achievements >= 95:
        goal = math.floor(info.achievements)
    else:
        goal = math.floor(info.achievements / 2) * 2
    return goal - info.achievements

async def generate_filter_50(args: List[str], qqid: Optional[int] = None, username: Optional[str] = None) -> Union[str, MessageSegment]:
    if 'help' in args:
        from .image import to_bytes_io
        return MessageSegment.image(to_bytes_io('''filter_50 帮助：
目前支持的筛选条件：
- diff(ds) 定数：diff12+ / ds=12.6 / diff12+-13.1 / ds=12.1~ / diff～13
- star 星数：star0 / star=1 / star1-3 / star=2~ / star～3
- achv 达成率：achv99.5-100.4999 / achv=99.5~ / achv～100
- lv 难度等级：lv绿 / lv=黄 / lv红-紫 / lv=紫~ / lv～白
- cat 谱面类型：cat=anime / cat=maimai+game [anime(流行/动漫), maimai, niconico, touhou(东方), game, ongeki]
- cmp 排序方式（从大到小）：cmpra / cmp=achv / cmp=slide/note
  + 个人成绩：ra rating(默认) / achv 达成率 / dxs DX分数占比 / cun 寸止 / suo 锁血
  + 谱面信息：diff(ds) 定数 / bpm / fit 拟合难度差
  + 谱面音符数：tap / hold / slide / touch / break / note
  + 寸止与锁血建议指定范围
- rev 倒序排序
例：f50 diff12-13 star=1 achv～100 cmp=achv rev'''))
    try:
        new_args = []
        for arg in args:
            if arg.startswith(('qq', 'qq=', 'qq＝')):
                qqid = int(arg[3:])
            elif arg.startswith(('user', 'user=', 'user＝')):
                username = arg[5:]
            else:
                new_args.append(arg)
        if username:
            qqid = None
        obj = await maiApi.query_user_dev(qqid=qqid, username=username)

        mai_info = UserInfo(**obj)
        try:
            filter, cmp = parse_filter_args(new_args)
        except ValueError as e:
            return str(e)

        charts_sd = [i for i in mai_info.records if mai.total_list.by_id(str(i.song_id)).basic_info.is_new == False]
        charts_dx = [i for i in mai_info.records if mai.total_list.by_id(str(i.song_id)).basic_info.is_new == True]
        chart_groups = [
            ChartInfoGroup('B35', charts_sd, 35),
            ChartInfoGroup('B15', charts_dx, 15),
        ]
        draw_best = ChartListDrawer(chart_groups, filter, cmp, mai_info, qqid)
        
        pic = await draw_best.draw()
        msg = MessageSegment.image(image_to_bytesio(pic))
    except UserNotFoundError as e:
        msg = str(e)
    except UserDisabledQueryError as e:
        msg = str(e)
    except Exception as e:
        log.error(traceback.format_exc())
        msg = f'未知错误：{type(e)}\n请联系Bot管理员'
    return msg