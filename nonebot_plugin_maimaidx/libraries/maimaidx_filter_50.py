import math
import traceback
from io import BytesIO
import re
from functools import cmp_to_key
from typing import List, Optional, Tuple, Union, Callable, overload

import httpx
from nonebot.adapters.onebot.v11 import MessageSegment
from PIL import Image, ImageDraw
from pydantic import BaseModel

from ..config import *
from .image import DrawText, image_to_bytesio
from .maimaidx_api_data import maiApi
from .maimaidx_error import *
from .maimaidx_music import download_music_pictrue, mai



class ChartInfo(BaseModel):
    
    achievements: float
    ds: float
    dxScore: int
    fc: str
    fs: str
    level: str
    level_index: int
    level_label: str
    ra: int
    rate: str
    song_id: int
    title: str
    type: str


class UserInfo(BaseModel):

    username: str
    rating: int
    additional_rating: int
    nickname: str
    plate: str
    records: List[ChartInfo]


class DrawFilter:

    basic = Image.open(maimaidir / 'b40_score_basic.png')
    advanced = Image.open(maimaidir / 'b40_score_advanced.png')
    expert = Image.open(maimaidir / 'b40_score_expert.png')
    master = Image.open(maimaidir / 'b40_score_master.png')
    remaster = Image.open(maimaidir / 'b40_score_remaster.png')
    logo = Image.open(maimaidir / 'logo.png').resize((378, 172))
    Name = Image.open(maimaidir / 'Name.png')
    ClassLevel = Image.open(maimaidir / 'UI_FBR_Class_00.png').resize((144, 87))
    rating = Image.open(maimaidir / 'UI_CMN_Shougou_Rainbow.png').resize((454, 50))
    dxstar = [Image.open(maimaidir / f'UI_RSL_DXScore_Star_0{_ + 1}.png').resize((20, 20)) for _ in range(3)]
    bg = Image.open(maimaidir / 'b40_bg.png').convert('RGBA')
    icon = Image.open(maimaidir / 'UI_Icon_309503.png').resize((214, 214))

    def __init__(self,
                 filter: Callable[[ChartInfo], bool],
                 cmp: Callable[[ChartInfo, ChartInfo], int],
                 UserInfo: UserInfo,
                 qqId: Optional[Union[int, str]] = None
                 ) -> None:

        self.userName = UserInfo.nickname
        self.plate = UserInfo.plate
        self.addRating = UserInfo.additional_rating
        self.Rating = UserInfo.rating
        self.qqId = qqId
        self.records = UserInfo.records
        # 选出is_new=False的records
        self.sdBest = [i for i in self.records if mai.total_list.by_id(str(i.song_id)).basic_info.is_new == False]
        self.dxBest = [i for i in self.records if mai.total_list.by_id(str(i.song_id)).basic_info.is_new == True]

        self.sdBest = [i for i in self.sdBest if filter(i)]
        self.dxBest = [i for i in self.dxBest if filter(i)]

        #按ra从高到低排序，取前35首
        self.sdBest = sorted(self.sdBest, key=cmp_to_key(cmp))[:35]
        self.dxBest = sorted(self.dxBest, key=cmp_to_key(cmp))[:15]

        # 把sdBest和dxBest的所有歌曲ra加起来
        self.Rating = sum([_.ra for _ in self.sdBest]) + sum([_.ra for _ in self.dxBest])


    def _findRaPic(self) -> str:
        if self.Rating < 1000:
            num = '01'
        elif self.Rating < 2000:
            num = '02'
        elif self.Rating < 4000:
            num = '03'
        elif self.Rating < 7000:
            num = '04'
        elif self.Rating < 10000:
            num = '05'
        elif self.Rating < 12000:
            num = '06'
        elif self.Rating < 13000:
            num = '07'
        elif self.Rating < 14000:
            num = '08'
        elif self.Rating < 14500:
            num = '09'
        elif self.Rating < 15000:
            num = '10'
        else:
            num = '11'
        return f'UI_CMN_DXRating_{num}.png'


    def _findMatchLevel(self) -> str:
        if self.addRating <= 10:
            num = f'{self.addRating:02d}'
        else:
            num = f'{self.addRating + 1:02d}'
        return f'UI_DNM_DaniPlate_{num}.png'


    async def whiledraw(self, data: List[ChartInfo], type: bool) -> None:
        # y为第一排纵向坐标，dy为各排间距
        y = 430 if type else 1670
        dy = 170

        TEXT_COLOR = [(255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255), (255, 255, 255, 255), (103, 20, 141, 255)]
        DXSTAR_DEST = [0, 330, 320, 310, 300, 290]

        for num, info in enumerate(data):
            if num % 5 == 0:
                x = 70
                y += dy if num != 0 else 0
            else:
                x += 416

            cover = Image.open(await download_music_pictrue(info.song_id)).resize((135, 135))
            version = Image.open(maimaidir / f'UI_RSL_MBase_Parts_{info.type}.png').resize((55, 19))
            rate = Image.open(maimaidir / f'UI_TTR_Rank_{score_Rank[info.rate]}.png').resize((95, 44))

            self._im.alpha_composite(self._diff[info.level_index], (x, y))
            self._im.alpha_composite(cover, (x + 5, y + 5))
            self._im.alpha_composite(version, (x + 80, y + 141))
            self._im.alpha_composite(rate, (x + 150, y + 98))
            if info.fc:
                fc = Image.open(maimaidir / f'UI_MSS_MBase_Icon_{fcl[info.fc]}.png').resize((45, 45))
                self._im.alpha_composite(fc, (x + 260, y + 98))
            if info.fs:
                fs = Image.open(maimaidir / f'UI_MSS_MBase_Icon_{fsl[info.fs]}.png').resize((45, 45))
                self._im.alpha_composite(fs, (x + 315, y + 98))
            
            dxscore = sum(mai.total_list.by_id(str(info.song_id)).charts[info.level_index].notes) * 3
            diff_sum_dx = info.dxScore / dxscore * 100
            dxtype, dxnum = dxScore(diff_sum_dx)
            for _ in range(dxnum):
                self._im.alpha_composite(DrawFilter.dxstar[dxtype], (x + DXSTAR_DEST[dxnum] + 20 * _, y + 74))

            self._tb.draw(x + 40, y + 148, 20, str(info.song_id), anchor='mm')
            title = info.title
            if coloumWidth(title) > 18:
                title = changeColumnWidth(title, 17) + '...'
            self._siyuan.draw(x + 155, y + 20, 20, title, TEXT_COLOR[info.level_index], anchor='lm')
            p, s = f'{info.achievements:.4f}'.split('.')
            r = self._tb.get_box(p, 32)
            self._tb.draw(x + 155, y + 70, 32, p, TEXT_COLOR[info.level_index], anchor='ld')
            self._tb.draw(x + 155 + r[2], y + 68, 22, f'.{s}%', TEXT_COLOR[info.level_index], anchor='ld')
            self._tb.draw(x + 340, y + 60, 18, f'{info.dxScore}/{dxscore}', TEXT_COLOR[info.level_index], anchor='mm')
            self._tb.draw(x + 155, y + 80, 22, f'{info.ds} -> {info.ra}', TEXT_COLOR[info.level_index], anchor='lm')


    async def draw(self):
        dx_rating = Image.open(maimaidir / self._findRaPic()).resize((300, 59))
        MatchLevel = Image.open(maimaidir / self._findMatchLevel()).resize((134, 55))
        self._diff = [DrawFilter.basic, DrawFilter.advanced, DrawFilter.expert, DrawFilter.master, DrawFilter.remaster]

        # 作图
        self._im = DrawFilter.bg.copy()

        self._im.alpha_composite(DrawFilter.logo, (5, 130))
        if self.plate:
            plate = Image.open(maimaidir / f'{self.plate}.png').resize((1420, 230))
        else:
            plate = Image.open(maimaidir / 'UI_Plate_300101.png').resize((1420, 230))
        self._im.alpha_composite(plate, (390, 100))
        self._im.alpha_composite(DrawFilter.icon, (398, 108))
        if self.qqId:
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.get(f'http://q1.qlogo.cn/g?b=qq&nk={self.qqId}&s=100')
                    qqLogo = Image.open(BytesIO(res.content))
                self._im.alpha_composite(Image.new('RGBA', (203, 203), (255, 255, 255, 255)), (404, 114))
                self._im.alpha_composite(qqLogo.convert('RGBA').resize((201, 201)), (405, 115))
            except Exception:
                pass
        self._im.alpha_composite(dx_rating, (620, 122))
        Rating = f'{self.Rating:05d}'
        for n, i in enumerate(Rating):
            self._im.alpha_composite(Image.open(maimaidir / f'UI_NUM_Drating_{i}.png').resize((28, 34)), (760 + 23 * n, 137))
        self._im.alpha_composite(DrawFilter.Name, (620, 200))
        self._im.alpha_composite(MatchLevel, (935, 205))
        self._im.alpha_composite(DrawFilter.ClassLevel, (926, 105))
        self._im.alpha_composite(DrawFilter.rating, (620, 275))

        text_im = ImageDraw.Draw(self._im)
        self._meiryo = DrawText(text_im, MEIRYO)
        self._siyuan = DrawText(text_im, SIYUAN)
        self._tb = DrawText(text_im, TBFONT)

        self._siyuan.draw(635, 235, 40, self.userName, (0, 0, 0, 255), 'lm')
        sdrating, dxrating = sum([_.ra for _ in self.sdBest]), sum([_.ra for _ in self.dxBest])
        self._tb.draw(847, 295, 28, f'B35: {sdrating} + B15: {dxrating} = {self.Rating}', (0, 0, 0, 255), 'mm', 3, (255, 255, 255, 255))
        self._meiryo.draw(900, 2365, 35, f'Designed by Yuri-YuzuChaN & BlueDeer233 | Generated by {maiconfig.botName} BOT', (103, 20, 141, 255), 'mm', 3, (255, 255, 255, 255))

        await self.whiledraw(self.sdBest, True)
        await self.whiledraw(self.dxBest, False)

        return self._im.resize((1760, 1920))


def dxScore(dx: float) -> Tuple[int, int]:
    """
    返回值为 `Tuple`： `(星星种类，数量)`
    """
    if dx <= 85:
        result = (0, 0)
    elif dx <= 90:
        result = (0, 1)
    elif dx <= 93:
        result = (0, 2)
    elif dx <= 95:
        result = (1, 3)
    elif dx <= 97:
        result = (1, 4)
    else:
        result = (2, 5)
    return result


def getCharWidth(o) -> int:
    widths = [
        (126, 1), (159, 0), (687, 1), (710, 0), (711, 1), (727, 0), (733, 1), (879, 0), (1154, 1), (1161, 0),
        (4347, 1), (4447, 2), (7467, 1), (7521, 0), (8369, 1), (8426, 0), (9000, 1), (9002, 2), (11021, 1),
        (12350, 2), (12351, 1), (12438, 2), (12442, 0), (19893, 2), (19967, 1), (55203, 2), (63743, 1),
        (64106, 2), (65039, 1), (65059, 0), (65131, 2), (65279, 1), (65376, 2), (65500, 1), (65510, 2),
        (120831, 1), (262141, 2), (1114109, 1),
    ]
    if o == 0xe or o == 0xf:
        return 0
    for num, wid in widths:
        if o <= num:
            return wid
    return 1


def coloumWidth(s: str) -> int:
    res = 0
    for ch in s:
        res += getCharWidth(ord(ch))
    return res


def changeColumnWidth(s: str, len: int) -> str:
    res = 0
    sList = []
    for ch in s:
        res += getCharWidth(ord(ch))
        if res <= len:
            sList.append(ch)
    return ''.join(sList)

@overload
def computeRa(ds: float, achievement: float) -> int: ...
@overload
def computeRa(ds: float, achievement: float, israte: bool = False) -> Tuple[int, str]: ...
def computeRa(ds: float, achievement: float, israte: bool = False) -> Union[int, Tuple[int, str]]:
    if achievement < 50:
        baseRa = 7.0
        rate = 'D'
    elif achievement < 60:
        baseRa = 8.0
        rate = 'C'
    elif achievement < 70:
        baseRa = 9.6
        rate = 'B'
    elif achievement < 75:
        baseRa = 11.2
        rate = 'BB'
    elif achievement < 80:
        baseRa = 12.0
        rate = 'BBB'
    elif achievement < 90:
        baseRa = 13.6
        rate = 'A'
    elif achievement < 94:
        baseRa = 15.2
        rate = 'AA'
    elif achievement < 97:
        baseRa = 16.8
        rate = 'AAA'
    elif achievement < 98:
        baseRa = 20.0
        rate = 'S'
    elif achievement < 99:
        baseRa = 20.3
        rate = 'Sp'
    elif achievement < 99.5:
        baseRa = 20.8
        rate = 'SS'
    elif achievement < 100:
        baseRa = 21.1
        rate = 'SSp'
    elif achievement < 100.5:
        baseRa = 21.6
        rate = 'SSS'
    else:
        baseRa = 22.4
        rate = 'SSSp'

    if israte:
        data = (math.floor(ds * (min(100.5, achievement) / 100) * baseRa), rate)
    else:
        data = math.floor(ds * (min(100.5, achievement) / 100) * baseRa)

    return data

def generateAchievementList(ds: float) -> List[float]:
    _achievementList = []
    for index, acc in enumerate(achievementList):
        if index == len(achievementList) - 1:
            continue
        _achievementList.append(acc)
        c_acc = (computeRa(ds, achievementList[index]) + 1) / ds / BaseRaSpp[index + 1] * 100
        c_acc = math.ceil(c_acc * 10000) / 10000
        while c_acc < achievementList[index + 1]:
            _achievementList.append(c_acc)
            c_acc = (computeRa(ds, c_acc + 0.0001) + 1) / ds / BaseRaSpp[index + 1] * 100
            c_acc = math.ceil(c_acc * 10000) / 10000
    _achievementList.append(100.5)
    return _achievementList

class BaseFilterArg:
    def valid(self, info: ChartInfo) -> bool:
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

        draw_best = DrawFilter(filter, cmp, mai_info, qqid)
        
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